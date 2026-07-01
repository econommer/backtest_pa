"""Vendor-agnostic market-data interface.

Neither the engine nor strategies bind to any data vendor; adapters (yfinance,
Stooq, Norgate, ...) implement this Protocol. Phase-1 free adapters carry
survivorship bias, which reports must flag (BACKTESTING_PLAN.md §3).
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


@runtime_checkable
class DataProvider(Protocol):
    """Point-in-time OHLCV, universe, and reference data."""

    def trading_calendar(self, start: date, end: date) -> list[date]:
        """Trading days in ``[start, end]`` inclusive."""
        ...

    def universe(self, on: date) -> list[str]:
        """Symbols that were index/universe members on ``on`` (delisted-inclusive in Phase 2)."""
        ...

    def history(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        fields: Sequence[str] = ("open", "high", "low", "close", "volume"),
    ) -> pd.DataFrame:
        """Daily bars for ``symbols`` over ``[start, end]`` for the given ``fields``."""
        ...

    def industry(self, symbol: str, on: date) -> str | None:
        """Point-in-time sector/industry for ``symbol`` (optional; None if unknown)."""
        ...

    def earnings_dates(self, symbol: str) -> list[date]:
        """Known earnings-announcement dates (gap-risk: avoid pre-earnings entries)."""
        ...

    def index(self, name: str, start: date, end: date) -> pd.Series:
        """Benchmark index close series over ``[start, end]``."""
        ...
