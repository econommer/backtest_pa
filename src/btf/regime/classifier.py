"""Regime engine — labels the market BULL/BEAR/RANGE/UNKNOWN (situation-awareness).

Strategy-agnostic: a classifier reads only a benchmark index series and knows
nothing about any strategy. The engine calls it once per bar with benchmark
history sliced to ``<= as_of`` (same look-ahead firewall as prices), then feeds
the label into ``MarketContext``. See M3 design spec §4.1.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd

from btf.core import Regime


@runtime_checkable
class RegimeClassifier(Protocol):
    """Turns benchmark history (ascending, ts <= as_of) into a regime label."""

    warmup_bars: int

    def classify(self, index_history: pd.Series) -> tuple[Regime, float | None]:
        """Return ``(regime, index_trend)`` for the most recent bar in ``index_history``."""
        ...


class SmaRegimeClassifier:
    """Close-vs-SMA (with SMA slope) regime rule — deterministic and testable."""

    def __init__(self, window: int = 200, slope_lookback: int = 20, band: float = 0.0) -> None:
        self.window = window
        self.slope_lookback = slope_lookback
        self.band = band
        self.warmup_bars = window

    def classify(self, index_history: pd.Series) -> tuple[Regime, float | None]:
        n = len(index_history)
        if n < self.window:
            return Regime.UNKNOWN, None

        closes = index_history.to_numpy(dtype=float)
        sma = float(closes[-self.window :].mean())
        close = float(closes[-1])
        index_trend = (close - sma) / sma if sma != 0 else 0.0

        # SMA slope: compare against the SMA `slope_lookback` bars earlier, if available.
        rising = falling = False
        prev_end = n - 1 - self.slope_lookback
        if prev_end + 1 >= self.window:
            sma_prev = float(closes[prev_end + 1 - self.window : prev_end + 1].mean())
            rising = sma > sma_prev
            falling = sma < sma_prev

        upper = sma * (1 + self.band)
        lower = sma * (1 - self.band)
        if close > upper and not falling:
            return Regime.BULL, index_trend
        if close < lower and not rising:
            return Regime.BEAR, index_trend
        return Regime.RANGE, index_trend
