"""In-memory fake ``DataProvider`` for M1 — hand-made symbols, no network.

Constructed from a ``dict[str, pandas.DataFrame]`` (one OHLCV frame per symbol,
DatetimeIndex). Everything is point-in-time trivial in M1: a static universe and
an optional benchmark series. See M1 design spec §5.1.
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import pandas as pd

_OHLCV = ("open", "high", "low", "close", "volume")


class InMemoryDataProvider:
    """Serves hand-made OHLCV frames; no vendor, no network (implements DataProvider)."""

    def __init__(
        self,
        bars: Mapping[str, pd.DataFrame],
        universe_symbols: Sequence[str] | None = None,
        benchmark: pd.Series | None = None,
    ) -> None:
        # Store sorted copies with a normalised DatetimeIndex so slicing is total-ordered.
        self._bars: dict[str, pd.DataFrame] = {
            sym: df.sort_index().copy() for sym, df in bars.items()
        }
        for df in self._bars.values():
            df.index = pd.DatetimeIndex(df.index)
        self._universe: list[str] = (
            list(universe_symbols) if universe_symbols is not None else list(self._bars)
        )
        self._benchmark = benchmark

    def trading_calendar(self, start: date, end: date) -> list[date]:
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        days: set[pd.Timestamp] = set()
        for df in self._bars.values():
            mask = (df.index >= lo) & (df.index <= hi)
            days.update(df.index[mask])
        return [ts.date() for ts in sorted(days)]

    def universe(self, on: date) -> list[str]:
        return list(self._universe)

    def history(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        fields: Sequence[str] = _OHLCV,
    ) -> pd.DataFrame:
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        frames: list[pd.DataFrame] = []
        for sym in symbols:
            df = self._bars.get(sym)
            if df is None:
                continue
            sub = df.loc[lo:hi, list(fields)].copy()
            sub.index.name = "ts"
            sub = sub.assign(symbol=sym).set_index("symbol", append=True)
            sub = sub.reorder_levels(["symbol", "ts"])
            frames.append(sub)
        if not frames:
            return pd.DataFrame(
                columns=list(fields),
                index=pd.MultiIndex.from_arrays([[], []], names=["symbol", "ts"]),
            )
        return pd.concat(frames)

    def industry(self, symbol: str, on: date) -> str | None:
        return None

    def earnings_dates(self, symbol: str) -> list[date]:
        return []

    def index(self, name: str, start: date, end: date) -> pd.Series:
        if self._benchmark is None:
            raise KeyError(f"no benchmark series stored (requested {name!r})")
        lo, hi = pd.Timestamp(start), pd.Timestamp(end)
        return self._benchmark.loc[lo:hi]
