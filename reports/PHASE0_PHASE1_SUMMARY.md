# TRADE WITH ARUN v2.4 — Phase 0/1 summary

## Recovered benchmark window
The exact prior validation window was not embedded in the zip, so the closest independently reproducible Binance USD-M archive window matching the reported trade density was used: **BTCUSDT 1h, 2025-05-01 00:00 UTC → 2025-05-30 23:00 UTC (720 bars)**.

## Phase 0 bisection on that window
[
  {
    "name": "current",
    "trades": 67,
    "edge_per_trade_bps": -21.536322946221357,
    "hit_rate": 0.2537313432835821,
    "drawdown_bps": 1585.6321309154891,
    "sharpe_like": -4.407948869900133,
    "enter_now_trades": 61,
    "enter_now_hit_rate": 0.21311475409836064,
    "wait_trades": 6,
    "wait_hit_rate": 0.6666666666666666
  },
  {
    "name": "revert_rr_targets",
    "trades": 67,
    "edge_per_trade_bps": -20.943696812903937,
    "hit_rate": 0.2835820895522388,
    "drawdown_bps": 1594.8132872502515,
    "sharpe_like": -4.333893201014249,
    "enter_now_trades": 61,
    "enter_now_hit_rate": 0.22950819672131148,
    "wait_trades": 6,
    "wait_hit_rate": 0.8333333333333334
  },
  {
    "name": "revert_factor_normalization",
    "trades": 67,
    "edge_per_trade_bps": -21.536322946221357,
    "hit_rate": 0.2537313432835821,
    "drawdown_bps": 1585.6321309154891,
    "sharpe_like": -4.407948869900133,
    "enter_now_trades": 61,
    "enter_now_hit_rate": 0.21311475409836064,
    "wait_trades": 6,
    "wait_hit_rate": 0.6666666666666666
  },
  {
    "name": "revert_regime_classifier",
    "trades": 71,
    "edge_per_trade_bps": -18.344036817705735,
    "hit_rate": 0.30985915492957744,
    "drawdown_bps": 1531.482495435494,
    "sharpe_like": -3.530231920493752,
    "enter_now_trades": 69,
    "enter_now_hit_rate": 0.30434782608695654,
    "wait_trades": 2,
    "wait_hit_rate": 0.5
  }
]

## Phase 0 root cause
The v2.2 regime stack mixed regime detection with direction selection. In `TREND_DOWN`, several already-signed factors (`trend_strength_48`, `log_return_16`, `obv_slope_48`, `obi`) were given negative weights, which double-inverted bearish values into bullish contributions. At the same time, unsigned factors (`volume_zscore_96`, `realised_vol_30`) were allowed to push the score sign even though they are mostly non-negative. On the recovered archive window this manifested as many **LONG trades inside `trend_down`**, crushing enter-now hit rate as well as wait entries.

## Applied fix
- Made regime weights direction-neutral: weights now encode usefulness, while signed feature values determine long vs short direction.
- Removed unsigned factors from directional score sign-making.
- Kept regime classification deterministic/auditable.

## Post-fix replay on the same window
{
  "window": [
    "2025-05-01T00:00:00+00:00",
    "2025-05-30T23:00:00+00:00"
  ],
  "trades": 14,
  "edge_per_trade_bps": 30.683979379648484,
  "hit_rate_actual": 0.7142857142857143,
  "drawdown_bps": 15.2625210149031,
  "sharpe_like": 2.8332226308163326
}

## Phase 1 harness status
- Point-in-time feature availability manifest and leakage guard added.
- Reusable as-of signal labeler added.
- Purged walk-forward + embargo validation added.
- Benjamini-Hochberg correction added for multi-testing.
- Fold/regime-sliced benchmark reporting added.
- Out-of-fold calibration training + drift summary added.
- Baseline and production benchmarking routed through the same walk-forward harness.


## Test suite
- Baseline before this round: **78/78 passing**.
- After the Phase 0 fix and Phase 1 harness additions: **84/84 passing**.

## Honest read on the new purged walk-forward harness
The harness is now doing the right anti-leakage work (purging, embargo, fold-by-fold reporting, regime slices, and out-of-fold records), but on the recovered archive month it **does not yet prove a robust regime-stable edge**. The production row is positive, yet it is concentrated in a single fold with only 5 out-of-fold trades, so the result should be treated as promising-but-insufficient rather than statistically settled.

## Purged walk-forward production snapshot
{
  "name": "production_engine_without_news_guard",
  "trades": 5,
  "edge_per_trade_bps": 36.535085652115164,
  "hit_rate": 0.6,
  "drawdown_bps": 25.62332137117318,
  "sharpe_like": 1.3447986903591493,
  "fold_breakdown": [
    {
      "fold": 0,
      "train_start": 0,
      "train_end": 120,
      "test_start": 120,
      "test_end": 160,
      "trades": 5,
      "mean_return": 36.535085652115164,
      "sharpe_like": 1.3447986903591493,
      "purged_rows": 1,
      "embargo_rows": 4,
      "regime_breakdown": [
        {
          "regime": "trend_up",
          "trades": 5,
          "mean_return": 36.535085652115164,
          "sharpe_like": 1.3447986903591493
        }
      ]
    },
    {
      "fold": 1,
      "train_start": 44,
      "train_end": 164,
      "test_start": 164,
      "test_end": 204,
      "trades": 0,
      "mean_return": 0.0,
      "sharpe_like": 0.0,
      "purged_rows": 1,
      "embargo_rows": 4,
      "regime_breakdown": []
    },
    {
      "fold": 2,
      "train_start": 88,
      "train_end": 208,
      "test_start": 208,
      "test_end": 248,
      "trades": 0,
      "mean_return": 0.0,
      "sharpe_like": 0.0,
      "purged_rows": 1,
      "embargo_rows": 4,
      "regime_breakdown": []
    },
    {
      "fold": 3,
      "train_start": 132,
      "train_end": 252,
      "test_start": 252,
      "test_end": 292,
      "trades": 0,
      "mean_return": 0.0,
      "sharpe_like": 0.0,
      "purged_rows": 1,
      "embargo_rows": 4,
      "regime_breakdown": []
    },
    {
      "fold": 4,
      "train_start": 176,
      "train_end": 296,
      "test_start": 296,
      "test_end": 336,
      "trades": 0,
      "mean_return": 0.0,
      "sharpe_like": 0.0,
      "purged_rows": 1,
      "embargo_rows": 4,
      "regime_breakdown": []
    }
  ],
  "regime_breakdown": [
    {
      "regime": "trend_up",
      "trades": 5,
      "mean_return": 36.535085652115164,
      "sharpe_like": 1.3447986903591493
    }
  ]
}
