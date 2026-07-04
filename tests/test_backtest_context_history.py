"""``BacktestContext.history`` contract pins (M6.5 speed-up harness).

``history()`` is on the do-not-change interface list for the M6.5 VCP
speed-up (see docs/superpowers/plans + code/CLAUDE.md): its *signature* and
*observable behaviour* must not change even though its internal slicing
strategy is being optimised away from ``df.loc[:as_of].tail(lookback)`` (an
O(full history) label-slice on every call) to a position-based lookup.

These tests pin every edge of the current (pre-optimisation) contract so a
faster internal implementation can be verified byte-for-byte against it:
  - ``lookback=None`` returns all bars <= as_of.
  - ``lookback=N`` returns exactly the trailing N bars <= as_of (or fewer if
    the visible history is shorter than N).
  - ``as_of`` that falls on a bar's exact date vs. a gap between bars (e.g. a
    weekend, or a symbol missing a mid-week print) behave identically to
    ``df.loc[:as_of_ts]`` (inclusive of the bar AT as_of; exclusive of
    anything after).
  - The returned frame's values, dtypes, and index are unchanged (a plain
    ``DataFrame.equals`` against a hand-computed ``loc``-based slice).
  - A symbol absent from the store returns an empty DataFrame.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from btf.context.backtest_context import BacktestContext
from btf.context.market import MarketContext
from btf.core import Regime


def _frame(n: int, start: date = date(2020, 1, 1), skip: set[int] | None = None) -> pd.DataFrame:
    """n business-day-ish bars starting at `start`; `skip` drops those offsets (gaps)."""
    skip = skip or set()
    rows = [i for i in range(n) if i not in skip]
    idx = pd.DatetimeIndex([pd.Timestamp(start) + timedelta(days=i) for i in rows])
    closes = [100.0 + i for i in rows]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000.0 + i for i in rows],
        },
        index=idx,
    )


def _ctx(store: dict[str, pd.DataFrame], as_of: date) -> BacktestContext:
    return BacktestContext(
        store=store,
        as_of=as_of,
        cash=0.0,
        equity=0.0,
        positions={},
        market=MarketContext(as_of=as_of, regime=Regime.UNKNOWN),
        universe=list(store.keys()),
    )


def _reference_history(df: pd.DataFrame, as_of: date, lookback: int | None) -> pd.DataFrame:
    """The ORIGINAL (pre-optimisation) implementation, verbatim, as the oracle."""
    visible = df.loc[: pd.Timestamp(as_of)]
    if lookback is not None:
        visible = visible.tail(lookback)
    return visible


@pytest.mark.parametrize("n", [0, 1, 5, 50, 169, 170, 171, 300])
@pytest.mark.parametrize("lookback", [None, 1, 10, 170, 171, 10_000])
def test_history_matches_reference_on_bar_dates(n: int, lookback: int | None) -> None:
    df = _frame(n)
    for offset in ([0, n // 2, n - 1] if n else [0]):
        as_of = (df.index[offset].date()) if n else date(2020, 1, 1)
        ctx = _ctx({"AAA": df}, as_of)
        got = ctx.history("AAA", lookback)
        want = _reference_history(df, as_of, lookback)
        assert got.equals(want), f"n={n} lookback={lookback} offset={offset}"


def test_history_matches_reference_on_gap_dates() -> None:
    """as_of falls BETWEEN two bars (a gap) — must still be inclusive-<=."""
    df = _frame(30, skip={10, 11, 12})
    as_of = date(2020, 1, 1) + timedelta(days=11)  # inside the gap
    for lookback in (None, 5, 100):
        ctx = _ctx({"AAA": df}, as_of)
        got = ctx.history("AAA", lookback)
        want = _reference_history(df, as_of, lookback)
        assert got.equals(want)


def test_history_before_first_bar_is_empty() -> None:
    df = _frame(10, start=date(2020, 2, 1))
    ctx = _ctx({"AAA": df}, date(2020, 1, 1))
    got = ctx.history("AAA", 5)
    assert got.empty


def test_history_missing_symbol_returns_empty_dataframe() -> None:
    df = _frame(10)
    ctx = _ctx({"AAA": df}, df.index[-1].date())
    got = ctx.history("ZZZ", 5)
    assert isinstance(got, pd.DataFrame)
    assert got.empty


def test_history_lookback_zero_matches_reference() -> None:
    df = _frame(20)
    as_of = df.index[-1].date()
    ctx = _ctx({"AAA": df}, as_of)
    got = ctx.history("AAA", 0)
    want = _reference_history(df, as_of, 0)
    assert got.equals(want)
