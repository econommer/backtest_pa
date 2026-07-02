"""UsageLedger invariants — the cap-safety bookkeeping (M6 spec D4)."""
from datetime import date
from pathlib import Path

import pytest

from btf.data.bloomberg.ledger import LedgerError, UsageLedger

D1 = date(2026, 7, 2)
D2 = date(2026, 7, 3)


def _ledger(tmp_path: Path) -> UsageLedger:
    return UsageLedger.load(tmp_path / "usage_ledger.json")


def test_missing_file_is_empty_ledger(tmp_path):
    led = _ledger(tmp_path)
    assert led.known_count == 0
    assert led.new_on(D1) == 0


def test_record_then_new_securities_excludes_known(tmp_path):
    led = _ledger(tmp_path)
    led.record(["AAPL US Equity", "MSFT US Equity"], on=D1)
    assert led.new_securities(["AAPL US Equity", "IBM US Equity"]) == ["IBM US Equity"]
    assert led.known_count == 2


def test_re_recording_known_security_adds_zero_new(tmp_path):
    led = _ledger(tmp_path)
    led.record(["AAPL US Equity"], on=D1)
    led.record(["AAPL US Equity"], on=D2)  # re-request: no new unique count
    assert led.new_on(D2) == 0
    assert led.known_count == 1


def test_allowance_decreases_with_new_securities_today(tmp_path):
    led = _ledger(tmp_path)
    led.record(["A US Equity", "B US Equity"], on=D1)
    assert led.allowance(D1, max_new_per_day=3) == 1
    assert led.allowance(D2, max_new_per_day=3) == 3  # fresh day, fresh budget
    led.record(["C US Equity", "D US Equity"], on=D1)
    assert led.allowance(D1, max_new_per_day=3) == 0  # floors at 0


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "usage_ledger.json"
    led = UsageLedger.load(path)
    led.record(["AAPL US Equity"], on=D1)
    reloaded = UsageLedger.load(path)
    assert reloaded.known_count == 1
    assert reloaded.new_on(D1) == 1
    assert reloaded.new_securities(["AAPL US Equity"]) == []


def test_corrupt_file_raises_ledger_error(tmp_path):
    path = tmp_path / "usage_ledger.json"
    path.write_text("{not json")
    with pytest.raises(LedgerError):
        UsageLedger.load(path)
