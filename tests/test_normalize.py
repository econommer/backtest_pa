"""Unit tests for the shared OHLCV normalization pipeline (M2).

The network adapters (yfinance/Stooq) hand vendor frames through
``normalize_ohlcv`` before serving them. These tests pin the hygiene the engine
depends on: tz-naive midnight index, lowercase float columns, dedup, dropna, sort.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from btf.data._normalize import normalize_ohlcv

_FIELDS = ("open", "high", "low", "close", "volume")


def _messy_raw() -> pd.DataFrame:
    """A deliberately dirty vendor frame: capitalized cols, tz-aware, unsorted,
    a duplicate timestamp, an all-NaN row, an extra column, intraday timestamps."""
    idx = pd.DatetimeIndex(
        [
            "2022-01-04 09:30:00",
            "2022-01-03 09:30:00",  # out of order
            "2022-01-05 16:00:00",
            "2022-01-05 16:00:00",  # duplicate day
            "2022-01-06 09:30:00",  # will be NaN
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
            "Adj Close": [10.2, 9.2, 11.2, 11.8, np.nan],  # dropped
        },
        index=idx,
    )


def test_normalize_shape_and_columns():
    out = normalize_ohlcv(_messy_raw(), _FIELDS)
    assert list(out.columns) == list(_FIELDS)
    assert out.index.name == "ts"
    assert all(str(out[c].dtype) == "float64" for c in _FIELDS)


def test_normalize_index_is_tznaive_midnight_sorted_unique():
    out = normalize_ohlcv(_messy_raw(), _FIELDS)
    idx = out.index
    assert idx.tz is None
    # every timestamp collapsed to midnight
    assert (idx == idx.normalize()).all()
    assert idx.is_monotonic_increasing
    assert idx.is_unique


def test_normalize_drops_nan_and_dedups_keep_last():
    out = normalize_ohlcv(_messy_raw(), _FIELDS)
    # 3 unique clean days remain (04, 03, and one 05); 06 is all-NaN → dropped
    assert list(out.index) == [
        pd.Timestamp("2022-01-03"),
        pd.Timestamp("2022-01-04"),
        pd.Timestamp("2022-01-05"),
    ]
    # dup kept the LAST row for 2022-01-05
    assert out.loc[pd.Timestamp("2022-01-05"), "open"] == 11.5


def test_normalize_empty_input_yields_contract_empty():
    out = normalize_ohlcv(pd.DataFrame(), _FIELDS)
    assert list(out.columns) == list(_FIELDS)
    assert len(out) == 0
    assert out.index.name == "ts"


def test_normalize_handles_multiindex_columns():
    """yfinance returns MultiIndex columns (field, ticker) for a single download."""
    idx = pd.DatetimeIndex(["2022-01-03", "2022-01-04"])
    raw = pd.DataFrame(
        {
            ("Open", "AAPL"): [10.0, 11.0],
            ("High", "AAPL"): [10.5, 11.5],
            ("Low", "AAPL"): [9.8, 10.8],
            ("Close", "AAPL"): [10.2, 11.2],
            ("Volume", "AAPL"): [1000, 1100],
        },
        index=idx,
    )
    raw.columns = pd.MultiIndex.from_tuples(raw.columns)
    out = normalize_ohlcv(raw, _FIELDS)
    assert list(out.columns) == list(_FIELDS)
    assert out.loc[pd.Timestamp("2022-01-04"), "close"] == 11.2
