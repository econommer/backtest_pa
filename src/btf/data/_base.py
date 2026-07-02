"""Shared base for cached network OHLCV adapters (M2).

A ``CachedOHLCVProvider`` turns a *fetch function* into a full ``DataProvider``:
it fetches each symbol once (cache-first), runs the raw frame through
``normalize_ohlcv``, and then **delegates the whole shape contract**
(``history``/``trading_calendar``/``universe``/``index``) to an internal
``InMemoryDataProvider``. Reusing M1's provider is deliberate: it guarantees the
network adapters' output is byte-for-byte identical to the in-memory one instead
of re-deriving the MultiIndex/empty-frame logic in two places.

The ``fetch_fn`` is an injectable seam ``(symbol, start, end) -> raw DataFrame``.
Real subclasses default it to yfinance / Stooq; tests inject a canned fetcher so
the normalization + cache paths run deterministically without a network.

Phase-1 free data carries **survivorship bias** (the universe is the static
symbol list you pass in — delisted names are absent) and offers no point-in-time
industry/RS. Reports must flag this (BACKTESTING_PLAN.md §3.3, §6).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

from btf.data._cache import cache_path, read_cache, write_cache
from btf.data._normalize import normalize_ohlcv
from btf.data.memory_provider import InMemoryDataProvider

_OHLCV = ("open", "high", "low", "close", "volume")

FetchFn = Callable[[str, date, date], pd.DataFrame]


class CachedOHLCVProvider:
    """Cache-first, normalizing OHLCV provider that delegates shape to InMemory."""

    #: subclasses set these
    source: str = "cached"

    def __init__(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        cache_dir: str | Path,
        benchmark_symbol: str | None = None,
        fetch_fn: FetchFn | None = None,
        fields: Sequence[str] = _OHLCV,
        adjusted: bool = True,
    ) -> None:
        self.start = start
        self.end = end
        self.adjusted = adjusted
        self._fields = tuple(fields)
        self._cache_dir = Path(cache_dir)
        self._fetch = fetch_fn or self._default_fetch
        self._requested = list(symbols)
        self._benchmark_symbol = benchmark_symbol

        bars: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            frame = self._load(sym)
            if not frame.empty:
                bars[sym] = frame

        benchmark: pd.Series | None = None
        if benchmark_symbol is not None:
            bframe = self._load(benchmark_symbol)
            if not bframe.empty:
                benchmark = bframe["close"].rename(benchmark_symbol)

        # Universe is the requested static symbol list (survivorship-biased, Phase 1).
        self._inner = InMemoryDataProvider(
            bars, universe_symbols=list(symbols), benchmark=benchmark
        )

    # ---- fetch + cache -------------------------------------------------------

    def _load(self, symbol: str) -> pd.DataFrame:
        """Return a normalized frame for ``symbol``: cache-hit, else fetch+cache."""
        path = cache_path(
            self._cache_dir, self.source, symbol, self.start, self.end, self.adjusted
        )
        cached = read_cache(path)
        if cached is not None:
            return cached
        raw = self._fetch(symbol, self.start, self.end)
        frame = normalize_ohlcv(raw, self._fields)
        write_cache(path, frame)
        return frame

    def is_cached(self, symbol: str) -> bool:
        """True if ``symbol``'s snapshot is already on disk (no fetch needed)."""
        path = cache_path(
            self._cache_dir, self.source, symbol, self.start, self.end, self.adjusted
        )
        return path.exists()

    def _default_fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        raise NotImplementedError("subclasses provide a default fetcher")

    # ---- DataProvider delegation --------------------------------------------

    def trading_calendar(self, start: date, end: date) -> list[date]:
        return self._inner.trading_calendar(start, end)

    def universe(self, on: date) -> list[str]:
        return self._inner.universe(on)

    def history(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        fields: Sequence[str] = _OHLCV,
    ) -> pd.DataFrame:
        return self._inner.history(symbols, start, end, fields)

    def industry(self, symbol: str, on: date) -> str | None:
        return None

    def earnings_dates(self, symbol: str) -> list[date]:
        return []

    def index(self, name: str, start: date, end: date) -> pd.Series:
        return self._inner.index(name, start, end)
