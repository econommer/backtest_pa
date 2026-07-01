"""Shared DataProvider.history() contract — enforced against EVERY provider (M2).

``assert_history_contract`` encodes the exact output shape the engine relies on.
It runs against:

* ``InMemoryDataProvider`` (M1, fed clean fixture data), and
* ``YFinanceDataProvider`` (M2 network adapter, fed a deliberately *dirty* raw
  vendor frame via an injected fetcher).

Both must satisfy the same assertions — that is the guarantee that the real
adapter's output is interchangeable with the in-memory one. The dirty-input case
also proves the normalization hygiene (tz, dedup, dropna, sort, dtypes).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from btf.data.memory_provider import InMemoryDataProvider
from btf.data.yfinance_provider import YFinanceDataProvider

_FIELDS = ("open", "high", "low", "close", "volume")


# --------------------------------------------------------------------------- #
# The shared contract
# --------------------------------------------------------------------------- #
def assert_history_contract(provider, symbols, start, end) -> pd.DataFrame:
    h = provider.history(symbols, start, end)

    # MultiIndex ["symbol", "ts"]
    assert isinstance(h.index, pd.MultiIndex)
    assert list(h.index.names) == ["symbol", "ts"]
    # columns exactly the OHLCV set, in order
    assert list(h.columns) == list(_FIELDS)
    # all numeric columns are float
    assert all(str(h[c].dtype) == "float64" for c in _FIELDS)

    if len(h) == 0:
        return h

    ts = h.index.get_level_values("ts")
    assert isinstance(ts, pd.DatetimeIndex)
    assert ts.tz is None  # tz-naive
    assert (ts == ts.normalize()).all()  # midnight
    assert not h.isna().any().any()  # no NaN rows

    # sorted within each symbol
    for _, grp in h.groupby(level="symbol"):
        sub_ts = grp.index.get_level_values("ts")
        assert sub_ts.is_monotonic_increasing
        assert sub_ts.is_unique
    return h


def assert_empty_contract(provider, start, end) -> None:
    """Requesting unknown symbols yields the canonical empty frame."""
    h = provider.history(["___NOPE___"], start, end)
    assert len(h) == 0
    assert list(h.columns) == list(_FIELDS)
    assert isinstance(h.index, pd.MultiIndex)
    assert list(h.index.names) == ["symbol", "ts"]


# --------------------------------------------------------------------------- #
# Provider builders
# --------------------------------------------------------------------------- #
def _clean_frame() -> pd.DataFrame:
    dates = pd.DatetimeIndex([date(2022, 1, 3), date(2022, 1, 4), date(2022, 1, 5)])
    return pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0],
            "high": [10.5, 11.5, 12.5],
            "low": [9.8, 10.8, 11.8],
            "close": [10.2, 11.2, 12.2],
            "volume": [1000.0, 1100.0, 1200.0],
        },
        index=dates,
    )


def _in_memory_provider() -> InMemoryDataProvider:
    return InMemoryDataProvider({"AAA": _clean_frame(), "BBB": _clean_frame()})


def _dirty_raw(symbol: str, start: date, end: date) -> pd.DataFrame:
    """A messy Yahoo-style frame: capitalized cols, tz-aware, unsorted, dup, NaN."""
    idx = pd.DatetimeIndex(
        [
            "2022-01-04 09:30:00",
            "2022-01-03 09:30:00",
            "2022-01-05 16:00:00",
            "2022-01-05 16:00:00",
            "2022-01-06 09:30:00",
        ],
        tz="America/New_York",
    )
    return pd.DataFrame(
        {
            "Open": [10.0, 9.0, 11.0, 11.5, np.nan],
            "High": [10.5, 9.5, 11.5, 12.0, np.nan],
            "Low": [9.8, 8.8, 10.8, 11.0, np.nan],
            "Close": [10.2, 9.2, 11.2, 11.8, np.nan],
            "Volume": [1000, 900, 1100, 1150, np.nan],
            "Adj Close": [10.2, 9.2, 11.2, 11.8, np.nan],
        },
        index=idx,
    )


def _yfinance_provider(tmp_path) -> YFinanceDataProvider:
    return YFinanceDataProvider(
        ["AAA", "BBB"],
        date(2022, 1, 1),
        date(2022, 1, 31),
        cache_dir=tmp_path,
        fetch_fn=_dirty_raw,
    )


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #
def test_in_memory_satisfies_contract():
    prov = _in_memory_provider()
    h = assert_history_contract(prov, ["AAA", "BBB"], date(2022, 1, 1), date(2022, 1, 31))
    assert set(h.index.get_level_values("symbol")) == {"AAA", "BBB"}
    assert_empty_contract(prov, date(2022, 1, 1), date(2022, 1, 31))


def test_yfinance_satisfies_contract(tmp_path):
    prov = _yfinance_provider(tmp_path)
    h = assert_history_contract(prov, ["AAA", "BBB"], date(2022, 1, 1), date(2022, 1, 31))
    assert set(h.index.get_level_values("symbol")) == {"AAA", "BBB"}
    assert_empty_contract(prov, date(2022, 1, 1), date(2022, 1, 31))


def test_both_providers_produce_identical_history(tmp_path):
    """The whole point: identical input data → byte-identical output frames."""

    def clean_raw(sym, start, end):
        # Same numbers as _clean_frame(), but in raw Yahoo shape (capitalized cols).
        f = _clean_frame().rename(
            columns={c: c.capitalize() for c in _FIELDS}
        )
        return f

    mem = _in_memory_provider().history(["AAA"], date(2022, 1, 1), date(2022, 1, 31))
    yf = YFinanceDataProvider(
        ["AAA"], date(2022, 1, 1), date(2022, 1, 31), cache_dir=tmp_path, fetch_fn=clean_raw
    ).history(["AAA"], date(2022, 1, 1), date(2022, 1, 31))
    pd.testing.assert_frame_equal(mem, yf)


def test_yfinance_cache_hit_skips_fetch(tmp_path):
    """Second construction must not call the fetcher — it reads the parquet cache."""
    calls: list[str] = []

    def counting_fetch(sym, start, end):
        calls.append(sym)
        return _dirty_raw(sym, start, end)

    kw = dict(cache_dir=tmp_path, fetch_fn=counting_fetch)
    YFinanceDataProvider(["AAA"], date(2022, 1, 1), date(2022, 1, 31), **kw)
    assert calls == ["AAA"]
    YFinanceDataProvider(["AAA"], date(2022, 1, 1), date(2022, 1, 31), **kw)
    assert calls == ["AAA"]  # unchanged → served from cache
