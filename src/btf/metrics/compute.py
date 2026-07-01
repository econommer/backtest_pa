"""``compute_metrics`` — honest core Metrics from trades + equity curve (M1).

All performance stats are in R units where noted (initial-stop-and-r-multiple).
``regime_breakdown`` and benchmark comparison are deferred to M3. See M1 design
spec §5.6, decision D2.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from btf.core import Trade
from btf.metrics.result import Metrics


def compute_metrics(trades: list[Trade], equity_curve: pd.Series) -> Metrics:
    num_trades = len(trades)
    max_dd_pct = _max_drawdown_pct(equity_curve)
    exposure = _exposure(trades, equity_curve)

    if num_trades == 0:
        return Metrics(
            num_trades=0,
            win_rate=0.0,
            avg_win_r=0.0,
            avg_loss_r=0.0,
            expectancy=0.0,
            profit_factor=0.0,
            max_losing_streak=0,
            max_drawdown_r=0.0,
            max_drawdown_pct=max_dd_pct,
            exposure=exposure,
        )

    winners = [t for t in trades if t.r_multiple > 0]
    losers = [t for t in trades if t.r_multiple < 0]
    win_rate = len(winners) / num_trades
    loss_rate = len(losers) / num_trades
    avg_win_r = sum(t.r_multiple for t in winners) / len(winners) if winners else 0.0
    avg_loss_r = abs(sum(t.r_multiple for t in losers) / len(losers)) if losers else 0.0
    expectancy = win_rate * avg_win_r - loss_rate * avg_loss_r

    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = -sum(t.pnl for t in trades if t.pnl < 0)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0

    return Metrics(
        num_trades=num_trades,
        win_rate=win_rate,
        avg_win_r=avg_win_r,
        avg_loss_r=avg_loss_r,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_losing_streak=_max_losing_streak(trades),
        max_drawdown_r=_max_drawdown_r(trades),
        max_drawdown_pct=max_dd_pct,
        exposure=exposure,
    )


def _max_losing_streak(trades: list[Trade]) -> int:
    longest = current = 0
    for t in trades:
        if t.r_multiple < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _max_drawdown_r(trades: list[Trade]) -> float:
    """Deepest peak-to-trough drop of the cumulative closed-trade-R curve."""
    peak = cum = 0.0
    max_dd = 0.0
    for t in trades:
        cum += t.r_multiple
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return max_dd


def _max_drawdown_pct(equity_curve: pd.Series) -> float:
    """Deepest peak-to-trough % decline of the equity curve."""
    if equity_curve is None or len(equity_curve) == 0:
        return 0.0
    peak = float("-inf")
    max_dd = 0.0
    for val in equity_curve.to_numpy(dtype=float):
        peak = max(peak, val)
        if peak > 0:
            max_dd = max(max_dd, (peak - val) / peak)
    return max_dd


def _exposure(trades: list[Trade], equity_curve: pd.Series) -> float:
    """Fraction of recorded days with >= 1 open position (derived from trade spans)."""
    if equity_curve is None or len(equity_curve) == 0:
        return 0.0
    spans = [(t.entry_ts, t.exit_ts) for t in trades]
    exposed = 0
    for ts in equity_curve.index:
        d: date = ts.date() if hasattr(ts, "date") else ts
        if any(entry <= d <= exit_ for entry, exit_ in spans):
            exposed += 1
    return exposed / len(equity_curve)
