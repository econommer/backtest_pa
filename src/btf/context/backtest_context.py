"""``BacktestContext`` — the concrete look-ahead firewall (implements Context).

Holds a *reference* to the engine's full per-symbol price store and slices it to
``<= as_of`` on every access, so a strategy can never reach a future bar. It takes
plain data only (store, as_of, snapshots) — it does not import ``Portfolio``, so
the firewall is unit-testable in isolation. See M1 design spec §4, §5.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import pandas as pd

from btf.context.market import MarketContext
from btf.core import Bar, Position


class BacktestContext:
    """Read-only, as-of view over a price store handed to a strategy each bar."""

    def __init__(
        self,
        store: Mapping[str, pd.DataFrame],
        as_of: date,
        cash: float,
        equity: float,
        positions: Mapping[str, Position],
        market: MarketContext,
        universe: Sequence[str],
    ) -> None:
        self._store = store
        self._as_of = as_of
        self._as_of_ts = pd.Timestamp(as_of)
        self._cash = cash
        self._equity = equity
        self._positions = dict(positions)
        self._market = market
        self._universe = list(universe)

    @property
    def as_of(self) -> date:
        return self._as_of

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def equity(self) -> float:
        return self._equity

    @property
    def positions(self) -> Mapping[str, Position]:
        return self._positions

    @property
    def market(self) -> MarketContext:
        return self._market

    @property
    def universe(self) -> Sequence[str]:
        return self._universe

    def history(self, symbol: str, lookback: int | None = None) -> pd.DataFrame:
        df = self._store.get(symbol)
        if df is None:
            return pd.DataFrame()
        # M6.5 speed-up: equivalent to `df.loc[:as_of]` (then `.tail(lookback)`)
        # but O(log n) positional lookup instead of an O(n) label-slice on the
        # full frame every call — this is on the strategy's per-bar hot path.
        # `searchsorted(..., side="right")` on the sorted index gives the same
        # "<= as_of" cut point `.loc[:as_of]` does, including when `as_of`
        # falls in a gap between bars. Bit-identical to the old implementation
        # (see tests/test_backtest_context_history.py, which diffs both against
        # a verbatim copy of the pre-speed-up code across on-bar/gap dates,
        # short/long/zero lookbacks, and missing symbols).
        end = df.index.searchsorted(self._as_of_ts, side="right")
        start = max(0, end - lookback) if lookback is not None else 0
        return df.iloc[start:end]

    def bar(self, symbol: str) -> Bar | None:
        df = self._store.get(symbol)
        if df is None or self._as_of_ts not in df.index:
            return None
        row = df.loc[self._as_of_ts]
        return Bar(
            symbol=symbol,
            ts=self._as_of,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
