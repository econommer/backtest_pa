"""The per-bar Context — the look-ahead firewall.

The engine constructs a Context each bar and hands it to ``Strategy.on_bar``.
Every accessor exposes only data with timestamp <= ``as_of``; the strategy
therefore cannot see future bars (bias defense, BACKTESTING_PLAN.md §6).
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Protocol, Sequence, runtime_checkable

import pandas as pd

from btf.context.market import MarketContext
from btf.core import Bar, Position


@runtime_checkable
class Context(Protocol):
    """Read-only view of the world at ``as_of`` handed to a strategy."""

    @property
    def as_of(self) -> date:
        """Timestamp of the current (most recent visible) bar."""
        ...

    @property
    def cash(self) -> float:
        """Available cash in the portfolio."""
        ...

    @property
    def equity(self) -> float:
        """Total portfolio equity (cash + marked-to-market positions)."""
        ...

    @property
    def positions(self) -> Mapping[str, Position]:
        """Open positions keyed by symbol (read-only snapshots)."""
        ...

    @property
    def market(self) -> MarketContext:
        """Current market regime / breadth (situation-awareness)."""
        ...

    @property
    def universe(self) -> Sequence[str]:
        """Point-in-time tradable symbols as of ``as_of``."""
        ...

    def history(self, symbol: str, lookback: int | None = None) -> pd.DataFrame:
        """OHLCV history for ``symbol`` with timestamps <= ``as_of``.

        ``lookback`` limits to the most recent N bars; None returns all
        available history. Never includes future bars.
        """
        ...

    def bar(self, symbol: str) -> Bar | None:
        """The current (``as_of``) bar for ``symbol``, or None if not trading."""
        ...
