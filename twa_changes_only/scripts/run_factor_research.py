from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, List

import httpx
import numpy as np
import pandas as pd

from twa.config import Settings
from twa.features.cross_exchange import normalise_funding
from twa.features.engineering import compute_all
from twa.models.types import Candle, Timeframe
from twa.regime.classifier import classify, regime_confidence
from twa.research.benchmarking import (
    BenchmarkRunner,
    BenchmarkConfig,
    PRODUCTION_ENGINE_NO_NEWS_GUARD,
    PRODUCTION_ENGINE_TECHNICAL_ONLY,
    PRODUCTION_ENGINE_WITH_NEWS_GUARD,
    ProductionVariant,
)
from twa.research.feature_discovery import CandidateSpec, FeatureDiscoveryEngine
from twa.research.lab import ResearchSession
from twa.research.public_market_data import (
    fetch_okx_funding_history,
    fetch_okx_hourly_candles,
    fetch_okx_open_interest_history,
    merge_public_derivatives_context,
)
from twa.research.walk_forward import WalkForwardConfig
from twa.signal.engine import FACTOR_KEYS, LEGACY_FACTOR_KEYS, compute_signal

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
REPORTS.mkdir(parents=True, exist_ok=True)


def _jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(type(obj).__name__)


async def _build_okx_session() -> tuple[ResearchSession, pd.DataFrame, str]:
    note = (
        "Research window uses OKX public spot+swap candles, funding-rate history, and open-interest history because "
        "Binance/Bybit public derivative endpoints are geo-restricted from this runtime. No private/authenticated "
        "endpoint was added. Historical order-book imbalance is unavailable from the accessible public feeds, so OBI "
        "is held at 0.0 during offline validation rather than fabricated."
    )
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        swap, spot, funding, oi = await asyncio.gather(
            fetch_okx_hourly_candles(client, "BTC-USDT-SWAP", bars=900),
            fetch_okx_hourly_candles(client, "BTC-USDT", bars=900),
            fetch_okx_funding_history(client, "BTC-USDT-SWAP", limit=200),
            fetch_okx_open_interest_history(client, "BTC-USDT-SWAP", period="1H"),
        )
    merged = merge_public_derivatives_context(swap, spot, funding, oi)
    candles = [
        Candle(
            symbol="BTCUSDT",
            exchange="okx",
            timeframe=Timeframe.H1,
            open_time=row.timestamp,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in merged.itertuples(index=False)
    ]
    settings = Settings(_env_file=None, data_dir=ROOT / "data")
    session = ResearchSession.from_candles(settings, "BTCUSDT", Timeframe.H1, candles)
    ff = session.feature_frame.merge(
        merged[["timestamp", "basis", "funding_rate", "oi_usd"]],
        on="timestamp",
        how="left",
    )
    ff["funding"] = ff["funding_rate"].fillna(0.0).apply(lambda v: normalise_funding(type("Funding", (), {"rate": v})()))
    ff["basis"] = ff["basis"].fillna(0.0).clip(-1.0, 1.0)
    ff["oi_delta"] = ff["oi_usd"].pct_change().fillna(0.0).clip(-0.05, 0.05) / 0.05
    ff["obi"] = 0.0
    session.feature_frame = ff
    return session, merged, note


def _variant(name: str, technical_only: bool, news_dampen: float, score_factor_keys: List[str]) -> ProductionVariant:
    return ProductionVariant(
        name=name,
        technical_only=technical_only,
        news_dampen=news_dampen,
        score_factor_keys=list(score_factor_keys),
    )


async def _run_variants(session: ResearchSession, score_factor_keys: List[str]) -> Dict[str, dict]:
    runner = BenchmarkRunner(session.settings)
    try:
        wf_cfg = WalkForwardConfig(train_bars=120, test_bars=40, step_bars=40, folds=5, target_column="forward_return_bps", embargo_bars=4)
        variants = [
            _variant(PRODUCTION_ENGINE_TECHNICAL_ONLY, True, 1.0, score_factor_keys),
            _variant(PRODUCTION_ENGINE_WITH_NEWS_GUARD, False, 0.85, score_factor_keys),
            _variant(PRODUCTION_ENGINE_NO_NEWS_GUARD, False, 1.0, score_factor_keys),
        ]
        out = {}
        for variant in variants:
            result = runner._production_engine(session, wf_cfg, variant=variant)
            out[variant.name] = result.model_dump(mode="json")
        bench = runner._build_report(session, BenchmarkConfig())
        out["baselines"] = [row.model_dump(mode="json") for row in bench.strategies if not row.name.startswith("production_engine_")]
        return out
    finally:
        await runner.close()


def _collect_factor_contribution_stats(session: ResearchSession) -> dict:
    target = session.target_frame(4).merge(
        session.feature_frame[["timestamp", "funding", "basis", "oi_delta", "obi"]],
        on="timestamp",
        how="left",
        suffixes=("", "_row"),
    )
    candle_idx = {c.open_time: idx for idx, c in enumerate(session.candles)}
    stats = {
        name: {"signals": 0, "sat_clip_rate": 0.0, "mean_abs_contribution": 0.0, "near_zero_share": 0.0}
        for name in LEGACY_FACTOR_KEYS
    }
    sat_counts = {name: 0 for name in LEGACY_FACTOR_KEYS}
    near_zero = {name: 0 for name in LEGACY_FACTOR_KEYS}
    abs_contribs = {name: [] for name in LEGACY_FACTOR_KEYS}
    signals = 0
    for row in target.iloc[-200:].itertuples(index=False):
        idx = candle_idx.get(row.timestamp)
        if idx is None or idx < 80:
            continue
        window = session.candles[:idx]
        features = {**compute_all(window)}
        features.update(
            {
                "funding": float(getattr(row, "funding", getattr(row, "funding_row", 0.0))),
                "basis": float(getattr(row, "basis", getattr(row, "basis_row", 0.0))),
                "oi_delta": float(getattr(row, "oi_delta", getattr(row, "oi_delta_row", 0.0))),
                "obi": float(getattr(row, "obi", getattr(row, "obi_row", 0.0))),
            }
        )
        regime = classify(features)
        reg_conf = regime_confidence(features, regime)
        sig = compute_signal(
            window,
            session.timeframe,
            {
                "funding": getattr(row, "funding", getattr(row, "funding_row", 0.0)),
                "basis": getattr(row, "basis", getattr(row, "basis_row", 0.0)),
                "oi_delta": getattr(row, "oi_delta", getattr(row, "oi_delta_row", 0.0)),
                "obi": getattr(row, "obi", getattr(row, "obi_row", 0.0)),
            },
            regime,
            reg_conf,
            score_factor_keys=list(LEGACY_FACTOR_KEYS),
        )
        if sig is None:
            continue
        signals += 1
        for contrib in sig.factor_contributions:
            stats[contrib.name]["signals"] += 1
            abs_contribs[contrib.name].append(abs(float(contrib.contribution)))
            if abs(float(contrib.norm_value)) >= 0.999:
                sat_counts[contrib.name] += 1
            if abs(float(contrib.contribution)) <= 0.002:
                near_zero[contrib.name] += 1
    for name in LEGACY_FACTOR_KEYS:
        n = max(stats[name]["signals"], 1)
        stats[name]["sat_clip_rate"] = sat_counts[name] / n
        stats[name]["mean_abs_contribution"] = float(np.mean(abs_contribs[name])) if abs_contribs[name] else 0.0
        stats[name]["near_zero_share"] = near_zero[name] / n
    return {"evaluated_signals": signals, "factors": stats}


def _build_candidate_frame(session: ResearchSession, merged: pd.DataFrame) -> tuple[pd.DataFrame, List[CandidateSpec]]:
    frame = session.target_frame(4).copy()
    frame["basis"] = frame["basis"].fillna(0.0)
    frame["funding_rate"] = frame["funding_rate"].fillna(0.0)
    frame["oi_usd"] = frame["oi_usd"].ffill().fillna(0.0)
    frame["price_ret_1"] = frame["close"].pct_change()
    frame["price_ret_4"] = frame["close"].pct_change(4)
    frame["oi_delta_raw_1"] = frame["oi_usd"].pct_change()
    frame["oi_delta_raw_4"] = frame["oi_usd"].pct_change(4)
    frame["basis_velocity_1"] = frame["basis"].diff(1)
    frame["basis_velocity_4"] = frame["basis"].diff(4)
    frame["basis_velocity_z_24"] = frame["basis_velocity_1"] / frame["basis_velocity_1"].rolling(24).std()
    frame["funding_z_21"] = (frame["funding_rate"] - frame["funding_rate"].rolling(21).mean()) / frame["funding_rate"].rolling(21).std()
    frame["funding_pct_63"] = frame["funding_rate"].rolling(63).apply(lambda s: pd.Series(s).rank(pct=True).iloc[-1], raw=False)
    frame["funding_extreme_mr_z"] = -frame["funding_z_21"]
    frame["funding_extreme_mr_pct"] = -(frame["funding_pct_63"] - 0.5) * 2.0
    frame["oi_price_divergence_1"] = -np.sign(frame["price_ret_1"].fillna(0.0)) * frame["oi_delta_raw_1"].fillna(0.0)
    frame["oi_price_divergence_4"] = -np.sign(frame["price_ret_4"].fillna(0.0)) * frame["oi_delta_raw_4"].fillna(0.0)
    liq_event = (frame["oi_delta_raw_1"] < 0.0) & (frame["price_ret_1"].abs() > frame["price_ret_1"].rolling(48).std())
    frame["liq_follow_1"] = np.where(liq_event, np.sign(frame["price_ret_1"]) * frame["price_ret_1"].abs() * frame["oi_delta_raw_1"].abs(), 0.0)
    frame["liq_fade_1"] = -frame["liq_follow_1"]
    frame["hour"] = frame["timestamp"].dt.hour
    frame["dow"] = frame["timestamp"].dt.dayofweek
    frame["hour_sin"] = np.sin(2 * np.pi * frame["hour"] / 24.0)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["hour"] / 24.0)
    frame["is_us_open"] = frame["hour"].isin([13, 14, 15, 16]).astype(float)
    frame["is_eu_open"] = frame["hour"].isin([7, 8, 9]).astype(float)
    frame["is_asia_open"] = frame["hour"].isin([0, 1, 2]).astype(float)
    frame["dow_mon"] = (frame["dow"] == 0).astype(float)
    frame["dow_fri"] = (frame["dow"] == 4).astype(float)

    base = merged[["timestamp", "close"]].copy().set_index("timestamp")
    h4_close = base["close"].resample("4h").last().dropna()
    d1_close = base["close"].resample("1d").last().dropna()
    frame = pd.merge_asof(frame.sort_values("timestamp"), np.log(h4_close / h4_close.shift(4)).rename("h4_log_return_16").reset_index(), on="timestamp", direction="backward")
    frame = pd.merge_asof(frame.sort_values("timestamp"), np.log(d1_close / d1_close.shift(4)).rename("d1_log_return_16").reset_index(), on="timestamp", direction="backward")
    frame["mtf_h4_agreement"] = np.sign(frame["log_return_16"]) * np.sign(frame["h4_log_return_16"]) * frame["log_return_16"].abs()
    frame["mtf_d1_agreement"] = np.sign(frame["log_return_16"]) * np.sign(frame["d1_log_return_16"]) * frame["log_return_16"].abs()

    rv_median = frame["realised_vol_30"].rolling(168).quantile(0.5)
    frame["mom_low_vol"] = frame["log_return_16"] * (frame["realised_vol_30"] <= rv_median).astype(float)
    frame["mom_high_vol"] = frame["log_return_16"] * (frame["realised_vol_30"] > rv_median).astype(float)
    frame["trend_low_vol"] = frame["trend_strength_48"] * (frame["realised_vol_30"] <= rv_median).astype(float)
    frame["trend_high_vol"] = frame["trend_strength_48"] * (frame["realised_vol_30"] > rv_median).astype(float)
    frame["meanrev_high_vol"] = -(frame["close"] / frame["close"].rolling(8).mean() - 1.0) * (frame["realised_vol_30"] > rv_median).astype(float)

    specs = [
        CandidateSpec("funding_extremes", "funding_extreme_mr_z", "Contrarian funding z-score vs 21-bar history."),
        CandidateSpec("funding_extremes", "funding_extreme_mr_pct", "Contrarian funding percentile vs 63-bar history."),
        CandidateSpec("oi_price_divergence", "oi_price_divergence_1", "1-bar OI change times opposite price sign."),
        CandidateSpec("oi_price_divergence", "oi_price_divergence_4", "4-bar OI change times opposite price sign."),
        CandidateSpec("basis_velocity", "basis_velocity_1", "1-bar change in perp-vs-spot basis."),
        CandidateSpec("basis_velocity", "basis_velocity_4", "4-bar change in perp-vs-spot basis."),
        CandidateSpec("basis_velocity", "basis_velocity_z_24", "Standardised basis velocity."),
        CandidateSpec("obi_persistence", "obi_persistence_3", "Historical OBI series unavailable from accessible public data; left untested."),
        CandidateSpec("vol_regime", "mom_low_vol", "1h momentum trusted only below rolling realised-vol median."),
        CandidateSpec("vol_regime", "mom_high_vol", "1h momentum trusted only above rolling realised-vol median."),
        CandidateSpec("vol_regime", "trend_low_vol", "Trend strength trusted only below rolling realised-vol median."),
        CandidateSpec("vol_regime", "trend_high_vol", "Trend strength trusted only above rolling realised-vol median."),
        CandidateSpec("vol_regime", "meanrev_high_vol", "Short-horizon mean reversion only in high-vol regime."),
        CandidateSpec("session", "hour_sin", "Cyclic hour-of-day encoding (sin)."),
        CandidateSpec("session", "hour_cos", "Cyclic hour-of-day encoding (cos)."),
        CandidateSpec("session", "is_us_open", "US session-open bars."),
        CandidateSpec("session", "is_eu_open", "EU session-open bars."),
        CandidateSpec("session", "is_asia_open", "Asia session-open bars."),
        CandidateSpec("session", "dow_mon", "Monday dummy."),
        CandidateSpec("session", "dow_fri", "Friday dummy."),
        CandidateSpec("multi_timeframe", "mtf_h4_agreement", "1h direction weighted by 4h trend agreement."),
        CandidateSpec("multi_timeframe", "mtf_d1_agreement", "1h direction weighted by 1d trend agreement."),
        CandidateSpec("liquidation_proxy", "liq_follow_1", "Follow same-direction move after OI drop + large price move."),
        CandidateSpec("liquidation_proxy", "liq_fade_1", "Fade same-direction move after OI drop + large price move."),
    ]
    return frame, specs


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, default=_jsonable), encoding="utf-8")


def _write_markdown_summary(
    path: Path,
    *,
    environment_note: str,
    part_a_stats: dict,
    legacy_results: Dict[str, dict],
    reduced_results: Dict[str, dict],
    candidate_report: dict,
    survivors: List[dict],
) -> None:
    flagged = [
        ("obv_slope_48", "Remove from directional scoring"),
        ("volume_zscore_96", "Remove from directional scoring"),
        ("realised_vol_30", "Keep only for regime/risk, not direction"),
    ]
    lines = [
        "# Factor-selection research summary",
        "",
        environment_note,
        "",
        "## Part A — flagged factor verification",
        "",
        f"Signals inspected for factor-contribution verification: **{part_a_stats['evaluated_signals']}**.",
        "",
        "| factor | mean abs contribution | clip saturation rate | near-zero share | action |",
        "|---|---:|---:|---:|---|",
    ]
    for name, action in flagged:
        row = part_a_stats["factors"][name]
        lines.append(
            f"| {name} | {row['mean_abs_contribution']:.4f} | {row['sat_clip_rate']:.3f} | {row['near_zero_share']:.3f} | {action} |"
        )
    lines.extend([
        "",
        "## Part A — 9-factor baseline vs reduced 6-factor benchmark",
        "",
        "### 9-factor legacy benchmark",
        "",
        "| variant | trades | edge/trade (bps) | hit rate | sharpe-like |",
        "|---|---:|---:|---:|---:|",
    ])
    for name in (PRODUCTION_ENGINE_WITH_NEWS_GUARD, PRODUCTION_ENGINE_NO_NEWS_GUARD, PRODUCTION_ENGINE_TECHNICAL_ONLY):
        row = legacy_results[name]
        lines.append(f"| {name} | {row['trades']} | {row['edge_per_trade_bps']:.2f} | {row['hit_rate']:.3f} | {row['sharpe_like']:.3f} |")
    lines.extend([
        "",
        "### Reduced 6-factor benchmark",
        "",
        "| variant | trades | edge/trade (bps) | hit rate | sharpe-like | change vs 9-factor |",
        "|---|---:|---:|---:|---:|---|",
    ])
    for name in (PRODUCTION_ENGINE_WITH_NEWS_GUARD, PRODUCTION_ENGINE_NO_NEWS_GUARD, PRODUCTION_ENGINE_TECHNICAL_ONLY):
        before = legacy_results[name]
        after = reduced_results[name]
        delta = after['edge_per_trade_bps'] - before['edge_per_trade_bps']
        verdict = "improved" if delta > 0.25 else ("worsened" if delta < -0.25 else "flat")
        lines.append(f"| {name} | {after['trades']} | {after['edge_per_trade_bps']:.2f} | {after['hit_rate']:.3f} | {after['sharpe_like']:.3f} | {verdict} ({delta:+.2f} bps) |")
    lines.extend([
        "",
        "## Part B — candidate discovery table",
        "",
        "| family | candidate | status | OOF IC | q-value | consistent folds | strategy edge (bps) | strategy hit | survives validation |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ])
    for row in candidate_report["rows"]:
        lines.append(
            f"| {row['family']} | {row['name']} | {row['status']} | {row['oof_ic']:.4f} | {row['q_value']:.4f} | {row['fold_sign_consistency']} | {row['strategy_edge_bps']:.2f} | {row['strategy_hit_rate']:.3f} | {row['survives_validation']} |"
        )
    lines.extend([
        "",
        "## Final verdict",
        "",
    ])
    if survivors:
        lines.append(f"Validated survivors: {', '.join(row['name'] for row in survivors)}.")
    else:
        lines.append(
            "No new candidate survived the full bar: multiple-testing-corrected IC screening, fold-sign consistency, regime stability, and positive out-of-fold directional walk-forward performance."
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    session, merged, note = await _build_okx_session()
    part_a_stats = _collect_factor_contribution_stats(session)
    legacy_results = await _run_variants(session, list(LEGACY_FACTOR_KEYS))
    reduced_results = await _run_variants(session, list(FACTOR_KEYS))
    candidate_frame, candidate_specs = _build_candidate_frame(session, merged)
    candidate_engine = FeatureDiscoveryEngine(horizon=4)
    candidate_report = candidate_engine.validate_candidates(
        session,
        candidate_frame,
        candidate_specs,
        walk_forward=WalkForwardConfig(train_bars=120, test_bars=40, step_bars=40, folds=5, target_column="forward_return", embargo_bars=4),
        screening_q=0.10,
        screening_abs_ic=0.10,
        min_consistent_folds=4,
        max_fold_std=0.20,
    ).model_dump(mode="json")
    survivors = [row for row in candidate_report["rows"] if row["survives_validation"]]

    _write_json(REPORTS / "part_a_factor_contributions.json", {"environment_note": note, **part_a_stats})
    _write_json(REPORTS / "part_a_benchmark_legacy_9.json", {"environment_note": note, "score_factor_keys": LEGACY_FACTOR_KEYS, **legacy_results})
    _write_json(REPORTS / "part_a_benchmark_reduced_6.json", {"environment_note": note, "score_factor_keys": FACTOR_KEYS, **reduced_results})
    _write_json(REPORTS / "part_b_candidate_results.json", {"environment_note": note, **candidate_report})
    _write_json(REPORTS / "final_benchmark.json", {"environment_note": note, "survivors": survivors, "final_results": reduced_results})
    _write_markdown_summary(
        REPORTS / "final_research_summary.md",
        environment_note=note,
        part_a_stats=part_a_stats,
        legacy_results=legacy_results,
        reduced_results=reduced_results,
        candidate_report=candidate_report,
        survivors=survivors,
    )


if __name__ == "__main__":
    asyncio.run(main())
