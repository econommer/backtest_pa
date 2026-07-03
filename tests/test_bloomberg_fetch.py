"""Stage-1 membership fetch: PIT monthly snapshots -> parquet + universe file."""
import json
from datetime import date

import pandas as pd
import pytest

from btf.data._cache import cache_path, read_cache
from btf.data.bloomberg.fetch import (
    BENCHMARK_SYMBOL,
    FAILURES_FILENAME,
    INDEX_SECURITY,
    MEMBERSHIP_FILENAME,
    bloomberg_dir,
    fetch_bars,
    fetch_benchmark,
    fetch_membership,
    member_symbol,
    month_ends,
    plan_bars,
    security_for,
    write_universe_file,
)
from btf.data.bloomberg.ledger import LedgerError, UsageLedger
from tests.bloomberg_fixtures import FakeSession, raw_bars


def test_month_ends_spans_inclusive_calendar_months():
    ends = month_ends(date(2020, 1, 15), date(2020, 4, 10))
    assert ends == [date(2020, 1, 31), date(2020, 2, 29), date(2020, 3, 31)]


def test_member_symbol_strips_exchange_code():
    assert member_symbol("AAPL UW") == "AAPL"
    assert member_symbol("BRK/B UN") == "BRK/B"


def test_security_for_appends_us_equity():
    assert security_for("AAPL") == "AAPL US Equity"


def test_fetch_membership_writes_parquet_and_counts_one_security(tmp_path):
    session = FakeSession(
        members_by_month={
            date(2020, 1, 31): ["AAA UW", "BBB UN"],
            date(2020, 2, 29): ["AAA UW", "CCC UN"],
        }
    )
    ledger = UsageLedger.load(tmp_path / "ledger.json")
    m = fetch_membership(
        session, ledger, tmp_path, date(2020, 1, 15), date(2020, 3, 10), on=TODAY
    )
    # Monthly PIT rows, symbols stripped of exchange codes.
    assert sorted(m[m["snapshot"] == pd.Timestamp("2020-01-31")]["symbol"]) == ["AAA", "BBB"]
    assert sorted(m[m["snapshot"] == pd.Timestamp("2020-02-29")]["symbol"]) == ["AAA", "CCC"]
    # Persisted for the provider.
    on_disk = pd.read_parquet(bloomberg_dir(tmp_path) / MEMBERSHIP_FILENAME)
    assert len(on_disk) == len(m)
    # The whole membership history costs exactly ONE unique security (spec D3).
    assert ledger.known_count == 1
    assert ledger.new_securities(["SPX Index"]) == []


def test_fetch_membership_raises_when_daily_budget_exhausted(tmp_path):
    """Budget check must happen BEFORE session call."""
    session = FakeSession(
        members_by_month={
            date(2020, 1, 31): ["AAA UW", "BBB UN"],
        }
    )
    ledger = UsageLedger.load(tmp_path / "ledger.json")
    # Pre-exhaust the budget by recording OTHER securities on TODAY.
    ledger.record(["AAA US Equity"], on=TODAY)
    # Now attempt to fetch with max_new_per_day=1; budget is full.
    with pytest.raises(LedgerError, match="daily budget exhausted"):
        fetch_membership(
            session, ledger, tmp_path, date(2020, 1, 15), date(2020, 2, 15), on=TODAY, max_new_per_day=1
        )
    # Session was never called (budget check happened first).
    assert session.calls == []


def test_write_universe_file_sorted_unique(tmp_path):
    m = pd.DataFrame(
        {
            "snapshot": pd.to_datetime(["2020-01-31", "2020-02-29", "2020-02-29"]),
            "symbol": ["BBB", "AAA", "BBB"],
        }
    )
    out = tmp_path / "universe.txt"
    symbols = write_universe_file(m, out)
    assert symbols == ["AAA", "BBB"]
    lines = [ln for ln in out.read_text().splitlines() if ln and not ln.startswith("#")]
    assert lines == ["AAA", "BBB"]


START, END = date(2020, 1, 15), date(2020, 3, 10)
TODAY = date(2026, 7, 2)


def _seeded(tmp_path, symbols):
    """Membership parquet on disk for `symbols`, all in one snapshot month."""
    m = pd.DataFrame(
        {"snapshot": [pd.Timestamp("2020-01-31")] * len(symbols), "symbol": symbols}
    )
    bdir = bloomberg_dir(tmp_path)
    bdir.mkdir(parents=True, exist_ok=True)
    m.to_parquet(bdir / MEMBERSHIP_FILENAME)
    return UsageLedger.load(tmp_path / "ledger.json")


def test_plan_bars_reports_counts_without_a_session(tmp_path):
    ledger = _seeded(tmp_path, ["AAA", "BBB", "CCC"])
    plan = plan_bars(ledger, tmp_path, START, END, on=TODAY, max_new_per_day=2)
    assert (plan.members, plan.cached, plan.failed, plan.todo) == (3, 0, 0, 3)
    assert plan.allowed_today == 2  # capped by the daily budget


def test_fetch_bars_writes_normalized_cache_and_records_ledger(tmp_path):
    ledger = _seeded(tmp_path, ["AAA", "BBB"])
    session = FakeSession(bars={
        "AAA US Equity": raw_bars("2020-01-15", 30, seed=1),
        "BBB US Equity": raw_bars("2020-01-15", 30, seed=2),
    })
    res = fetch_bars(session, ledger, tmp_path, START, END, on=TODAY)
    assert sorted(res.fetched) == ["AAA", "BBB"] and not res.failed
    cached = read_cache(cache_path(tmp_path, "bloomberg", "AAA", START, END, True))
    assert list(cached.columns) == ["open", "high", "low", "close", "volume"]
    assert ledger.known_count == 2


def test_fetch_bars_hard_stops_before_exceeding_daily_budget(tmp_path):
    ledger = _seeded(tmp_path, ["AAA", "BBB", "CCC"])
    session = FakeSession(bars={
        f"{s} US Equity": raw_bars("2020-01-15", 30) for s in ("AAA", "BBB", "CCC")
    })
    res = fetch_bars(
        session, ledger, tmp_path, START, END, on=TODAY, max_new_per_day=2
    )
    assert len(res.fetched) == 2 and res.budget_stopped and res.remaining == 1
    assert ledger.new_on(TODAY) == 2  # never exceeded
    # Next day: budget resets, the remainder completes.
    res2 = fetch_bars(
        session, ledger, tmp_path, START, END, on=date(2026, 7, 3), max_new_per_day=2
    )
    assert res2.fetched == ["CCC"] and not res2.budget_stopped


def test_fetch_bars_resumes_skipping_cached_and_failed(tmp_path):
    ledger = _seeded(tmp_path, ["AAA", "GONE"])
    session = FakeSession(bars={"AAA US Equity": raw_bars("2020-01-15", 30)})
    res = fetch_bars(session, ledger, tmp_path, START, END, on=TODAY)
    assert res.fetched == ["AAA"] and res.failed == {"GONE": "no data"}
    failures = json.loads((bloomberg_dir(tmp_path) / FAILURES_FILENAME).read_text())
    assert "GONE" in failures
    # Re-run: nothing to do — cached + failed both skipped, no new session calls.
    calls_before = len(session.calls)
    res2 = fetch_bars(session, ledger, tmp_path, START, END, on=TODAY)
    assert res2.fetched == [] and res2.remaining == 0
    assert len(session.calls) == calls_before


def test_fetch_bars_zero_allowance_makes_no_session_calls(tmp_path):
    """Budget already exhausted: no session call should occur."""
    ledger = _seeded(tmp_path, ["X", "Y"])
    # Pre-exhaust the budget by recording OTHER securities (not in the fetch set).
    ledger.record(["OTHER1 US Equity", "OTHER2 US Equity"], on=TODAY)
    session = FakeSession(bars={
        "X US Equity": raw_bars("2020-01-15", 30),
        "Y US Equity": raw_bars("2020-01-15", 30),
    })
    res = fetch_bars(session, ledger, tmp_path, START, END, on=TODAY, max_new_per_day=2)
    # No fetches, budget stopped, remaining == 2 (both still to-do).
    assert res.fetched == [] and res.budget_stopped and res.remaining == 2
    # Verify no ("bars", ...) entry in session.calls — budget check prevented any request.
    bar_calls = [c for c in session.calls if c[0] == "bars"]
    assert bar_calls == []


def test_fetch_bars_budget_exhausted_across_batches(tmp_path):
    """Budget exhausted between batch 1 and batch 3: exactly 2 fetched, batch 3 stopped."""
    ledger = _seeded(tmp_path, ["X", "Y", "Z"])
    session = FakeSession(bars={
        "X US Equity": raw_bars("2020-01-15", 30),
        "Y US Equity": raw_bars("2020-01-15", 30),
        "Z US Equity": raw_bars("2020-01-15", 30),
    })
    # max_new_per_day=2, batch_size=1 => batch 1 (X), batch 2 (Y) succeed; batch 3 (Z) stopped.
    res = fetch_bars(
        session, ledger, tmp_path, START, END, on=TODAY, max_new_per_day=2, batch_size=1
    )
    assert sorted(res.fetched) == ["X", "Y"]
    assert res.budget_stopped and res.remaining == 1
    # Cap never exceeded: ledger must show exactly 2 new on TODAY.
    assert ledger.new_on(TODAY) == 2


def test_fetch_benchmark_caches_spx_bars(tmp_path):
    ledger = UsageLedger.load(tmp_path / "ledger.json")
    session = FakeSession(bars={INDEX_SECURITY: raw_bars("2020-01-15", 30)})
    fetch_benchmark(session, ledger, tmp_path, START, END, on=TODAY)
    cached = read_cache(cache_path(tmp_path, "bloomberg", BENCHMARK_SYMBOL, START, END, True))
    assert cached is not None and not cached.empty
