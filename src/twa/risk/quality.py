"""Trade-quality scoring (used by backtest and live evaluator).

This is a *pure* function: takes a historical signal outcome and returns
a 0..1 quality score.  Useful for confidence calibration.
"""
from __future__ import annotations

import numpy as np


def trade_quality_score(pnl_bps: float, mfe: float, mae: float, holding_bars: int) -> float:
    """Score ∈ [0,1] emphasising:

      * Positive PnL (heavily)
      * Less adverse excursion (MAE)
      * Reasonable holding time (penalises too-short, too-long)
    """
    pnl = float(pnl_bps)
    base = 1.0 / (1.0 + np.exp(-pnl / 25.0))     # logistic on PnL in bps
    mae_adj = float(np.exp(-abs(mae) / max(abs(mfe), 1.0)))
    hold_adj = float(np.exp(-abs(holding_bars - 16) / 16.0))
    return float(np.clip(base * 0.6 + mae_adj * 0.25 + hold_adj * 0.15, 0.0, 1.0))
