"""Offline DataProvider over the Bloomberg parquet snapshot (M6 spec D2/D3).

Reads ONLY what the fetch script cached — a cache miss raises with the fetch
command instead of silently going to the network, so a backtest can never
consume Bloomberg quota. ``universe(on)`` is point-in-time: the members at the
latest monthly snapshot <= ``on`` (delisted included), which the engine hands
to strategies each bar (basic_engine passes ``data.universe(t)`` into the
context). Shape contracts delegate to InMemoryDataProvider, same as the
Phase-1 adapters.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

from btf.data._cache import cache_path, read_cache
from btf.data.bloomberg.fetch import MEMBERSHIP_FILENAME, bloomberg_dir
from btf.data.memory_provider import InMemoryDataProvider

_OHLCV = ("open", "high", "low", "close", "volume")
_FETCH_HINT = "run: python scripts/fetch_bloomberg_snapshot.py --stage {stage} --confirm"


class SnapshotError(RuntimeError):
    """The offline snapshot is incomplete — message names the fetch command."""


class BloombergSnapshotProvider:
    """Serves cached Bloomberg bars + PIT S&P 500 universe; never fetches."""

    source = "bloomberg"

    def __init__(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        cache_dir: str | Path,
        benchmark_symbol: str = "SPX",
        strict: bool = False,
    ) -> None:
        mpath = bloomberg_dir(cache_dir) / MEMBERSHIP_FILENAME
        if not mpath.exists():
            raise SnapshotError(
                f"membership snapshot missing: {mpath}\n"
                + _FETCH_HINT.format(stage="membership")
            )
        m = pd.read_parquet(mpath)
        self._members: dict[pd.Timestamp, list[str]] = {
            ts: grp["symbol"].tolist() for ts, grp in m.groupby("snapshot")
        }
        self._snapshot_dates: list[pd.Timestamp] = sorted(self._members)

        bars: dict[str, pd.DataFrame] = {}
        missing: list[str] = []
        for sym in symbols:
            frame = read_cache(cache_path(cache_dir, "bloomberg", sym, start, end, True))
            if frame is None or frame.empty:
                missing.append(sym)
            else:
                bars[sym] = frame
        if missing and strict:
            raise SnapshotError(
                f"{len(missing)} symbol(s) missing cached bars "
                f"(e.g. {missing[:5]})\n" + _FETCH_HINT.format(stage="bars")
            )
        # A 100% miss is never a genuine coverage gap — it means the (start, end)
        # used here doesn't match what was fetched (a cache-key mismatch), so fail
        # loudly even when strict=False rather than silently returning an empty book.
        if symbols and missing and len(missing) == len(symbols):
            raise SnapshotError(
                f"all {len(symbols)} requested symbol(s) have no cached bars for "
                f"({start}, {end}) — likely a start/end mismatch with the fetched "
                f"snapshot window, not a coverage gap\n"
                + _FETCH_HINT.format(stage="bars")
            )
        #: Symbols requested but not on disk — surfaced as coverage stats (D10).
        self.missing_symbols: list[str] = missing

        benchmark: pd.Series | None = None
        bframe = read_cache(
            cache_path(cache_dir, "bloomberg", benchmark_symbol, start, end, True)
        )
        if bframe is None or bframe.empty:
            raise SnapshotError(
                f"benchmark {benchmark_symbol!r} has no cached bars for ({start}, {end})\n"
                + _FETCH_HINT.format(stage="membership")
            )
        benchmark = bframe["close"].rename(benchmark_symbol)
        self._inner = InMemoryDataProvider(
            bars, universe_symbols=list(symbols), benchmark=benchmark
        )

    # ---- point-in-time universe (the M6 point) --------------------------------

    def universe(self, on: date) -> list[str]:
        ts = pd.Timestamp(on)
        past = [d for d in self._snapshot_dates if d <= ts]
        return list(self._members[past[-1]]) if past else []

    # ---- DataProvider delegation ----------------------------------------------

    def trading_calendar(self, start: date, end: date) -> list[date]:
        return self._inner.trading_calendar(start, end)

    def history(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        fields: Sequence[str] = _OHLCV,
    ) -> pd.DataFrame:
        return self._inner.history(symbols, start, end, fields)

    def industry(self, symbol: str, on: date) -> str | None:
        return None  # deferred (spec D9) — zero extra unique-security cost later

    def earnings_dates(self, symbol: str) -> list[date]:
        return []  # deferred (spec D9)

    def index(self, name: str, start: date, end: date) -> pd.Series:
        return self._inner.index(name, start, end)
