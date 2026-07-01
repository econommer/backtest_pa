"""Backtest output objects. All metrics are in R units (initial-stop-and-r-multiple).

expectancy = win_rate * avg_win_R - loss_rate * avg_loss_R  (BACKTESTING_PLAN.md §4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import pandas as pd

from btf.core import Regime, Trade


@dataclass(frozen=True, slots=True)
class Metrics:
    """Summary statistics for a set of trades, in R units."""

    num_trades: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    expectancy: float
    profit_factor: float
    max_losing_streak: int
    max_drawdown_r: float
    max_drawdown_pct: float
    exposure: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """The complete, reproducible output of one backtest run."""

    config: Mapping[str, object]
    equity_curve: pd.Series
    metrics: Metrics
    benchmark_curve: pd.Series | None = None
    trades: list[Trade] = field(default_factory=list)
    regime_breakdown: dict[Regime, Metrics] = field(default_factory=dict)
