"""BloombergSnapshotProvider: offline reads + point-in-time universe (M6 spec D2/D3)."""
from datetime import date

import pandas as pd
import pytest

from btf.data._cache import cache_path, write_cache
from btf.data._normalize import normalize_ohlcv
from btf.data.bloomberg import BloombergSnapshotProvider
from btf.data.bloomberg.fetch import MEMBERSHIP_FILENAME, bloomberg_dir
from btf.data.bloomberg.snapshot_provider import SnapshotError
from btf.data.provider import DataProvider
from tests.bloomberg_fixtures import raw_bars

START, END = date(2020, 1, 15), date(2020, 3, 10)


def _snapshot(tmp_path, membership_rows, bar_symbols):
    bdir = bloomberg_dir(tmp_path)
    bdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(membership_rows, columns=["snapshot", "symbol"]).to_parquet(
        bdir / MEMBERSHIP_FILENAME
    )
    for i, sym in enumerate(bar_symbols):
        frame = normalize_ohlcv(raw_bars("2020-01-15", 30, seed=i))
        write_cache(cache_path(tmp_path, "bloomberg", sym, START, END, True), frame)


MEMBERSHIP = [
    (pd.Timestamp("2020-01-31"), "AAA"),
    (pd.Timestamp("2020-01-31"), "BBB"),
    (pd.Timestamp("2020-02-29"), "AAA"),
    (pd.Timestamp("2020-02-29"), "CCC"),
]


def test_conforms_to_data_provider_protocol(tmp_path):
    _snapshot(tmp_path, MEMBERSHIP, ["AAA", "BBB", "CCC", "SPX"])
    p = BloombergSnapshotProvider(["AAA", "BBB", "CCC"], START, END, cache_dir=tmp_path)
    assert isinstance(p, DataProvider)


def test_universe_is_point_in_time(tmp_path):
    _snapshot(tmp_path, MEMBERSHIP, ["AAA", "BBB", "CCC", "SPX"])
    p = BloombergSnapshotProvider(["AAA", "BBB", "CCC"], START, END, cache_dir=tmp_path)
    assert p.universe(date(2020, 1, 20)) == []           # before first snapshot
    assert sorted(p.universe(date(2020, 2, 10))) == ["AAA", "BBB"]   # Jan snapshot
    assert sorted(p.universe(date(2020, 3, 5))) == ["AAA", "CCC"]    # Feb: BBB left
    # No future member ever leaks into an earlier date (no look-ahead).
    assert "CCC" not in p.universe(date(2020, 2, 10))


def test_history_and_index_served_offline(tmp_path):
    _snapshot(tmp_path, MEMBERSHIP, ["AAA", "SPX"])
    p = BloombergSnapshotProvider(
        ["AAA"], START, END, cache_dir=tmp_path, benchmark_symbol="SPX"
    )
    hist = p.history(["AAA"], START, END)
    assert not hist.empty and list(hist.index.names) == ["symbol", "ts"]
    idx = p.index("SPX", START, END)
    assert len(idx) > 0


def test_missing_bars_collected_not_fetched(tmp_path):
    _snapshot(tmp_path, MEMBERSHIP, ["AAA", "SPX"])  # BBB/CCC bars absent
    p = BloombergSnapshotProvider(["AAA", "BBB", "CCC"], START, END, cache_dir=tmp_path)
    assert sorted(p.missing_symbols) == ["BBB", "CCC"]
    with pytest.raises(SnapshotError, match="fetch_bloomberg_snapshot"):
        BloombergSnapshotProvider(
            ["AAA", "BBB", "CCC"], START, END, cache_dir=tmp_path, strict=True
        )


def test_missing_membership_parquet_raises_with_fetch_command(tmp_path):
    with pytest.raises(SnapshotError, match="fetch_bloomberg_snapshot"):
        BloombergSnapshotProvider(["AAA"], START, END, cache_dir=tmp_path)
