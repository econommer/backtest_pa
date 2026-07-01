"""``YFinanceDataProvider`` — Phase-1 free daily bars via yfinance (M2).

Split/dividend-**adjusted** OHLCV (``auto_adjust=True``), normalized and cached.
This is the primary Phase-1 adapter; ``StooqDataProvider`` is the fallback.

Survivorship caveat (BACKTESTING_PLAN.md §3.3): yfinance only serves currently
listed symbols, so any static universe you pass is survivorship-biased — reports
must say so. ``yfinance`` is an optional dependency (``pip install btf[data]``).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from btf.data._base import CachedOHLCVProvider


class YFinanceDataProvider(CachedOHLCVProvider):
    """Cached, adjusted, normalized daily bars from Yahoo Finance."""

    source = "yfinance"

    def _default_fetch(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        import yfinance as yf  # imported lazily so the dep stays optional

        # yfinance treats ``end`` as exclusive; +1 day makes the range inclusive
        # to match the provider contract (history() slices are inclusive).
        raw = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
            actions=False,
        )
        if raw is None:
            return pd.DataFrame()
        return raw
