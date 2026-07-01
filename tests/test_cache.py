"""Parquet cache round-trip + keying (M2)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from btf.data._cache import cache_path, read_cache, write_cache


def _frame() -> pd.DataFrame:
    idx = pd.DatetimeIndex([date(2022, 1, 3), date(2022, 1, 4)], name="ts")
    return pd.DataFrame(
        {
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.8, 10.8],
            "close": [10.2, 11.2],
            "volume": [1000.0, 1100.0],
        },
        index=idx,
    )


def test_path_keyed_by_source_symbol_range_adjusted(tmp_path):
    p = cache_path(tmp_path, "yfinance", "AAPL", date(2018, 1, 1), date(2023, 1, 1), True)
    assert p.parent.name == "yfinance"
    name = p.name
    assert "AAPL" in name and "2018-01-01" in name and "2023-01-01" in name
    assert name.endswith(".parquet")
    # different range / adjusted flag / source → different file
    assert cache_path(tmp_path, "yfinance", "AAPL", date(2019, 1, 1), date(2023, 1, 1), True) != p
    assert cache_path(tmp_path, "yfinance", "AAPL", date(2018, 1, 1), date(2023, 1, 1), False) != p
    assert cache_path(tmp_path, "stooq", "AAPL", date(2018, 1, 1), date(2023, 1, 1), True) != p


def test_write_then_read_roundtrip_preserves_frame(tmp_path):
    p = cache_path(tmp_path, "yfinance", "AAPL", date(2022, 1, 1), date(2022, 2, 1), True)
    assert read_cache(p) is None  # miss before write
    df = _frame()
    write_cache(p, df)
    got = read_cache(p)
    assert got is not None
    pd.testing.assert_frame_equal(got, df)
    assert got.index.name == "ts"


def test_read_missing_returns_none(tmp_path):
    assert read_cache(tmp_path / "nope.parquet") is None
