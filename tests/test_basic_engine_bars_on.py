"""``BasicEngine._bars_on`` positional-cursor speed-up identity (M6.5).

``_bars_on`` currently does a per-symbol, per-bar ``df.loc[ts]`` scalar lookup
(`ts not in df.index` then `df.loc[ts]`) over the FULL per-symbol frame, every
bar of the run. The M6.5 plan replaces this with a precomputed positional
structure (numpy OHLCV arrays + a timestamp->index map per symbol) built once,
so each day's lookup is O(1) instead of re-walking the index.

This test pins the CURRENT behaviour with a verbatim oracle copy of the
original ``_bars_on`` body, then diffs it against the engine's (possibly
rewritten/inlined) bar-lookup on a fixture store that has:
  - a symbol with a genuine mid-series gap (no bar on some date, but bars
    both before and after — must be simply absent from that day's dict, not
    an error),
  - a symbol that stops trading entirely partway through (delisted — must be
    absent from every day's dict after its last bar, exactly like a gap looks
    from _bars_on's point of view; delisting-vs-gap disambiguation is a
    caller-level concern in ``BasicEngine.run``, not ``_bars_on`` itself),
  - a symbol trading the full window (present every day),
  - a requested symbol entirely absent from the store (must be silently
    skipped, not an error).

If ``_bars_on`` remains a separable staticmethod after the optimisation, this
test calls it directly. If it gets inlined into ``run()``, the same behaviour
is additionally covered end-to-end by the existing delisting/gap tests in
tests/test_stopout.py, which must keep passing unchanged.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from btf.core import Bar
from btf.engine.basic_engine import BasicEngine


def _frame(start: date, n: int, skip: set[int] | None = None) -> pd.DataFrame:
    skip = skip or set()
    rows = [i for i in range(n) if i not in skip]
    idx = pd.DatetimeIndex([pd.Timestamp(start) + timedelta(days=i) for i in rows])
    closes = [100.0 + i for i in rows]
    return pd.DataFrame(
        {
            "open": [c - 0.2 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1000.0 + i for i in rows],
        },
        index=idx,
    )


def _oracle_bars_on(store: dict[str, pd.DataFrame], symbols: list[str], t: date) -> dict[str, Bar]:
    """Verbatim copy of BasicEngine._bars_on's original body (the pre-speed-up oracle)."""
    ts = pd.Timestamp(t)
    bars: dict[str, Bar] = {}
    for sym in symbols:
        df = store.get(sym)
        if df is None or ts not in df.index:
            continue
        row = df.loc[ts]
        bars[sym] = Bar(
            symbol=sym,
            ts=t,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
        )
    return bars


def _build_fixture_store() -> dict[str, pd.DataFrame]:
    start = date(2020, 1, 1)
    return {
        "FULL": _frame(start, 40),                       # trades every day
        "GAPPY": _frame(start, 40, skip={10, 11, 20}),    # mid-series holes
        "DELISTED": _frame(start, 15),                    # stops trading after day 15
    }


def test_bars_on_matches_oracle_across_gaps_delisting_and_missing_symbol() -> None:
    store = _build_fixture_store()
    cursors = BasicEngine._build_cursors(store)
    requested = ["FULL", "GAPPY", "DELISTED", "NEVER_CACHED"]
    all_dates = sorted(
        {ts.date() for df in store.values() for ts in df.index}
        | {date(2020, 1, 1) + timedelta(days=i) for i in range(45)}  # also probe past the end
    )

    for t in all_dates:
        want = _oracle_bars_on(store, requested, t)
        got = BasicEngine._bars_on(cursors, requested, t)
        assert set(got) == set(want), f"symbol-set mismatch at {t}: {set(got)} vs {set(want)}"
        for sym in want:
            assert got[sym] == want[sym], f"bar mismatch for {sym} at {t}: {got[sym]} vs {want[sym]}"


def test_bars_on_empty_store_and_empty_symbol_list() -> None:
    assert BasicEngine._bars_on({}, [], date(2020, 1, 1)) == {}
    empty_cursors = BasicEngine._build_cursors({"AAA": _frame(date(2020, 1, 1), 5)})
    assert BasicEngine._bars_on(empty_cursors, [], date(2020, 1, 1)) == {}
