"""Stage-1 membership fetch: PIT monthly snapshots -> parquet + universe file."""
from datetime import date

import pandas as pd
import pytest

from btf.data.bloomberg.fetch import (
    MEMBERSHIP_FILENAME,
    bloomberg_dir,
    fetch_membership,
    member_symbol,
    month_ends,
    security_for,
    write_universe_file,
)
from btf.data.bloomberg.ledger import LedgerError, UsageLedger
from tests.bloomberg_fixtures import FakeSession

TODAY = date(2026, 7, 2)


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
