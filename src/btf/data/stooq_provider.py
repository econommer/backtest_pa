"""``StooqDataProvider`` — Phase-1 free daily bars via Stooq (M2 fallback).

The fallback when yfinance is unavailable/rate-limited. Stooq serves a plain CSV
per symbol (``Date,Open,High,Low,Close,Volume``); we fetch it with ``pandas`` and
hand it through the shared normalization + cache. US tickers use the ``.us``
suffix (e.g. ``aapl.us``), added automatically when no suffix is present.

Stooq daily history is split/dividend-adjusted. Same survivorship caveat as the
yfinance adapter (BACKTESTING_PLAN.md §3.3). No extra dependency beyond pandas.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from btf.data._base import CachedOHLCVProvider

_STOOQ_URL = "https://stooq.com/q/d/l/?s={sym}&i=d&d1={d1}&d2={d2}"


class StooqDataProvider(CachedOHLCVProvider):
    """Cached, normalized daily bars from Stooq CSV downloads."""

    source = "stooq"

    @staticmethod
    def _stooq_symbol(symbol: str) -> str:
        s = symbol.lower()
        # US equities need the .us market suffix; leave indices/others (with a
        # '.' or '^') as the caller provided.
        if "." not in s and not s.startswith("^"):
            s = f"{s}.us"
        return s

    def _default_fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        url = _STOOQ_URL.format(
            sym=self._stooq_symbol(symbol),
            d1=start.strftime("%Y%m%d"),
            d2=end.strftime("%Y%m%d"),
        )
        raw = pd.read_csv(url)
        if raw.empty or "Date" not in raw.columns:
            return pd.DataFrame()
        raw = raw.set_index("Date")
        raw.index = pd.DatetimeIndex(raw.index)
        return raw
