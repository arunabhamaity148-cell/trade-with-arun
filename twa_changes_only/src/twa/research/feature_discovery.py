"""Candidate feature generation and predictive scoring utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from scipy.stats import spearmanr

from twa.logging import get_logger
from twa.research.lab import ResearchSession
from twa.research.utils import benjamini_hochberg, rank_ic, split_slices
from twa.research.walk_forward import WalkForwardConfig

log = get_logger("research.feature_discovery")

_BASE_COLUMNS = {"timestamp", "symbol", "open", "high", "low", "close", "volume", "regime"}


class FeatureDiscoveryRow(BaseModel):
    name: str
    ic: float
    stability: float
    subperiod_ics: List[float] = Field(default_factory=list)
    redundancy_corr: float = 0.0
    redundant_with: str = ""


class FeatureDiscoveryReport(BaseModel):
    symbol: str
    timeframe: str
    horizon: int
    rows: List[FeatureDiscoveryRow]


class CandidateValidationRow(BaseModel):
    family: str
    name: str
    status: str = "tested"
    notes: str = ""
    oof_ic: float = 0.0
    p_value: float = 1.0
    q_value: float = 1.0
    fold_ics: List[float] = Field(default_factory=list)
    fold_sign_consistency: int = 0
    fold_std: float = 0.0
    strategy_trades: int = 0
    strategy_edge_bps: float = 0.0
    strategy_hit_rate: float = 0.0
    regime_ics: Dict[str, float] = Field(default_factory=dict)
    survives_screening: bool = False
    survives_validation: bool = False


class CandidateValidationReport(BaseModel):
    symbol: str
    timeframe: str
    horizon: int
    rows: List[CandidateValidationRow] = Field(default_factory=list)


@dataclass(frozen=True)
class CandidateSpec:
    family: str
    name: str
    notes: str = ""


class FeatureDiscoveryEngine:
    """Generate, score, and rank candidate features for a research session."""

    def __init__(self, horizon: int = 4, subperiods: int = 3):
        self.horizon = horizon
        self.subperiods = subperiods

    def discover(self, session: ResearchSession) -> FeatureDiscoveryReport:
        target = session.target_frame(self.horizon)
        candidates = self._candidate_frame(session)
        joined = target[["timestamp", "forward_return"]].merge(candidates, on="timestamp", how="inner")
        prod = target.drop(columns=["forward_return", "forward_return_bps"], errors="ignore")
        prod_features = [c for c in prod.columns if c not in _BASE_COLUMNS]
        rows: List[FeatureDiscoveryRow] = []
        for name in [c for c in joined.columns if c not in {"timestamp", "forward_return"}]:
            ic = rank_ic(joined[name], joined["forward_return"])
            sub_ics = []
            for slc in split_slices(len(joined), self.subperiods):
                piece = joined.iloc[slc]
                sub_ics.append(rank_ic(piece[name], piece["forward_return"]))
            stability = float(1.0 / (1.0 + np.std(sub_ics or [0.0])))
            redundancy_corr = 0.0
            redundant_with = ""
            aligned = prod.merge(joined[["timestamp", name]], on="timestamp", how="inner")
            for prod_name in prod_features:
                corr = aligned[[prod_name, name]].corr().iloc[0, 1] if len(aligned) >= 8 else 0.0
                corr = 0.0 if np.isnan(corr) else float(abs(corr))
                if corr > redundancy_corr:
                    redundancy_corr = corr
                    redundant_with = prod_name
            rows.append(FeatureDiscoveryRow(
                name=name,
                ic=float(ic),
                stability=stability,
                subperiod_ics=[float(v) for v in sub_ics],
                redundancy_corr=float(redundancy_corr),
                redundant_with=redundant_with,
            ))
        rows.sort(key=lambda r: (abs(r.ic), r.stability), reverse=True)
        log.info("research.feature_discovery.complete", symbol=session.symbol, rows=len(rows))
        return FeatureDiscoveryReport(symbol=session.symbol, timeframe=session.timeframe.value, horizon=self.horizon, rows=rows)

    def validate_candidates(
        self,
        session: ResearchSession,
        candidate_frame: pd.DataFrame,
        candidate_specs: List[CandidateSpec],
        *,
        walk_forward: Optional[WalkForwardConfig] = None,
        screening_q: float = 0.10,
        screening_abs_ic: float = 0.10,
        min_consistent_folds: int = 4,
        max_fold_std: float = 0.20,
    ) -> CandidateValidationReport:
        target = session.target_frame(self.horizon)
        joined = target.merge(candidate_frame, on="timestamp", how="left")
        wf_cfg = walk_forward or WalkForwardConfig(
            train_bars=120,
            test_bars=40,
            step_bars=40,
            folds=5,
            target_column="forward_return",
            embargo_bars=4,
        )

        rows: List[CandidateValidationRow] = []
        tested_rows: List[CandidateValidationRow] = []
        p_values: List[float] = []
        for spec in candidate_specs:
            if spec.name not in joined.columns:
                rows.append(CandidateValidationRow(
                    family=spec.family,
                    name=spec.name,
                    status="unavailable",
                    notes=spec.notes or "candidate column missing from frame",
                ))
                continue
            evaluated = self._evaluate_candidate(joined, spec, wf_cfg)
            rows.append(evaluated)
            tested_rows.append(evaluated)
            p_values.append(evaluated.p_value)

        q_values = benjamini_hochberg(p_values)
        for row, q_value in zip(tested_rows, q_values):
            row.q_value = float(q_value)
            row.survives_screening = abs(row.oof_ic) >= screening_abs_ic and row.q_value <= screening_q
            same_sign = row.fold_sign_consistency >= min_consistent_folds
            stable = row.fold_std <= max_fold_std
            regime_signs = [np.sign(v) for v in row.regime_ics.values() if abs(v) >= 0.05]
            regime_stable = len({int(v) for v in regime_signs if v != 0}) <= 1
            strategy_edge_ok = row.strategy_edge_bps > 0.0 and row.strategy_hit_rate >= 0.5
            row.survives_validation = bool(row.survives_screening and same_sign and stable and regime_stable and strategy_edge_ok)

        rows.sort(key=lambda row: (row.status != "tested", -abs(row.oof_ic), row.q_value, row.name))
        log.info("research.feature_discovery.validated", symbol=session.symbol, tested=len(tested_rows), total=len(rows))
        return CandidateValidationReport(
            symbol=session.symbol,
            timeframe=session.timeframe.value,
            horizon=self.horizon,
            rows=rows,
        )

    def _evaluate_candidate(self, frame: pd.DataFrame, spec: CandidateSpec, cfg: WalkForwardConfig) -> CandidateValidationRow:
        fold_ics: List[float] = []
        fold_strategy_returns: List[float] = []
        fold_strategy_hits: List[bool] = []
        oof_pieces: List[pd.DataFrame] = []
        embargo_shift = 0
        for fold in range(cfg.folds):
            train_start = fold * cfg.step_bars + embargo_shift
            train_end = train_start + cfg.train_bars
            test_start = train_end
            test_end = test_start + cfg.test_bars
            if test_end > len(frame):
                break
            test = frame.iloc[test_start:test_end].copy()
            valid = test[[spec.name, "forward_return", "regime"]].dropna()
            if valid.empty:
                fold_ics.append(0.0)
                embargo_shift += int(cfg.embargo_bars)
                continue
            ic, _ = self._spearman(valid[spec.name], valid["forward_return"])
            fold_ics.append(ic)
            direction = np.sign(valid[spec.name]).astype(float)
            strategy_returns = direction * valid["forward_return"] * 10_000.0
            active = strategy_returns[direction != 0]
            fold_strategy_returns.extend(active.tolist())
            fold_strategy_hits.extend((active > 0).tolist())
            oof_pieces.append(valid.assign(fold=fold))
            embargo_shift += int(cfg.embargo_bars)

        if oof_pieces:
            oof = pd.concat(oof_pieces, ignore_index=True)
            oof_ic, p_value = self._spearman(oof[spec.name], oof["forward_return"])
            regime_ics = {}
            for regime, grp in oof.groupby("regime"):
                if len(grp) >= 20:
                    regime_ics[str(regime)] = self._spearman(grp[spec.name], grp["forward_return"])[0]
        else:
            oof_ic, p_value, regime_ics = 0.0, 1.0, {}

        same_sign = sum(1 for ic in fold_ics if np.sign(ic) == np.sign(oof_ic) and abs(ic) >= 0.005)
        returns = pd.Series(fold_strategy_returns, dtype=float)
        hit_rate = float(np.mean(fold_strategy_hits)) if fold_strategy_hits else 0.0
        edge = float(returns.mean()) if not returns.empty else 0.0
        return CandidateValidationRow(
            family=spec.family,
            name=spec.name,
            status="tested",
            notes=spec.notes,
            oof_ic=float(oof_ic),
            p_value=float(p_value),
            fold_ics=[float(v) for v in fold_ics],
            fold_sign_consistency=int(same_sign),
            fold_std=float(np.std(fold_ics)) if fold_ics else 0.0,
            strategy_trades=int(len(returns)),
            strategy_edge_bps=edge,
            strategy_hit_rate=hit_rate,
            regime_ics={k: float(v) for k, v in regime_ics.items()},
        )

    def _candidate_frame(self, session: ResearchSession) -> pd.DataFrame:
        df = session.frame.copy().reset_index(drop=True)
        close = df["close"]
        volume = df["volume"]
        high = df["high"]
        low = df["low"]
        ret = np.log(close).diff()
        out = pd.DataFrame({
            "timestamp": df["timestamp"],
            "ret_1": ret,
            "ret_3": np.log(close / close.shift(3)),
            "ret_8": np.log(close / close.shift(8)),
            "mean_rev_8": close / close.rolling(8).mean() - 1.0,
            "momentum_24": close / close.shift(24) - 1.0,
            "vol_8": ret.rolling(8).std(),
            "vol_24": ret.rolling(24).std(),
            "range_pct_8": ((high - low) / close).rolling(8).mean(),
            "volume_ratio_8": volume / volume.rolling(8).mean(),
            "volume_trend_16": volume.ewm(span=16, adjust=False).mean().pct_change(),
            "wick_balance_8": (((high - close) - (close - low)) / close).rolling(8).mean(),
            "breakout_distance_20": close / high.rolling(20).max() - 1.0,
            "compression_20": ((high.rolling(20).max() - low.rolling(20).min()) / close).replace([np.inf, -np.inf], np.nan),
        })
        return out.dropna().reset_index(drop=True)

    @staticmethod
    def _spearman(left: pd.Series, right: pd.Series) -> tuple[float, float]:
        valid = pd.concat([left, right], axis=1).dropna()
        if len(valid) < 8:
            return 0.0, 1.0
        res = spearmanr(valid.iloc[:, 0], valid.iloc[:, 1])
        corr = 0.0 if res.correlation is None or np.isnan(res.correlation) else float(res.correlation)
        p_value = 1.0 if res.pvalue is None or np.isnan(res.pvalue) else float(res.pvalue)
        return corr, p_value
