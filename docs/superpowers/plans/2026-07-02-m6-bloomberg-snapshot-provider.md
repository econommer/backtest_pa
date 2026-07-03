# M6 — Bloomberg Snapshot Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Survivorship-free Phase-2 data: a budgeted Bloomberg fetch pipeline + an offline snapshot `DataProvider`, ending in the first credible VCP report on point-in-time S&P 500 membership, 2010–2025.

**Architecture:** Snapshot-first (spec D2): only the fetch script opens a blpapi session; every request is pre-counted against a persistent `UsageLedger` with a hard daily budget; `BloombergSnapshotProvider` reads parquet only and serves a point-in-time `universe(on)` from monthly membership snapshots. Engine and strategies stay vendor-blind.

**Tech Stack:** Python 3.11+, pandas/pyarrow (already present), `blpapi` as a new *optional* dependency (lazy import, never touched by tests).

**Spec:** `docs/superpowers/specs/2026-07-02-m6-phase2-bloomberg-data-design.md` — decisions cited as D1–D10.

**Branch:** work on `m6-bloomberg-data` (create from `main` before Task 1).

## Global Constraints

- **Never break the Bloomberg data cap** — budget check happens BEFORE every request; default `--max-new-per-day 300`; nothing fetches without `--confirm` (spec D4, D5).
- `blpapi` is imported **only** inside `src/btf/data/bloomberg/session.py`, lazily; `tests/` must never import it (spec §1 acceptance 3).
- All new code: type hints, `ruff` + `mypy src` clean. Run `python -m pytest` from repo root; 121 existing tests must stay green.
- Cache layout reuses `btf.data._cache.cache_path(cache_dir, "bloomberg", symbol, start, end, adjusted=True)` and `btf.data._normalize.normalize_ohlcv` (spec D6).
- Symbols in the framework are bare Bloomberg tickers (`AAPL`, `BRK/B`); the ledger stores full security strings (`AAPL US Equity`). `cache_path` already slugs `/`.
- Frozen interfaces: `DataProvider` (src/btf/data/provider.py) and `Strategy` are NOT modified.

---

### Task 1: UsageLedger — persistent request accounting with a hard daily budget

**Files:**
- Create: `src/btf/data/bloomberg/__init__.py`
- Create: `src/btf/data/bloomberg/ledger.py`
- Test: `tests/test_bloomberg_ledger.py`

**Interfaces:**
- Consumes: nothing new (stdlib + json).
- Produces (used by Tasks 3, 4, 7):
  - `class LedgerError(RuntimeError)`
  - `class UsageLedger` with:
    - `UsageLedger.load(path: str | Path) -> UsageLedger` (missing file ⇒ empty ledger; corrupt ⇒ `LedgerError`)
    - `.save() -> None`
    - `.known_count -> int` (property: total unique securities ever)
    - `.new_securities(secs: Sequence[str]) -> list[str]` (order-preserving, not yet known)
    - `.new_on(on: date) -> int` (securities first recorded on `on`)
    - `.allowance(on: date, max_new_per_day: int) -> int` (`max(0, max_new_per_day - new_on(on))`)
    - `.record(secs: Sequence[str], on: date) -> None` (adds new secs stamped `on`, bumps `daily[on]` request count, saves)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bloomberg_ledger.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bloomberg_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf.data.bloomberg'`

- [ ] **Step 3: Implement**

```python
# src/btf/data/bloomberg/__init__.py
"""Bloomberg Phase-2 data package (M6). Offline provider exported in Task 5."""
```

```python
# src/btf/data/bloomberg/ledger.py
"""Persistent Bloomberg usage accounting — the cap-safety bookkeeping (M6 spec D4).

Bloomberg's Desktop API meters (opaquely) daily hits and *monthly unique
securities*; unique securities never un-count. The ledger therefore records
every security we have EVER requested (so re-requests are free) plus per-day
new-security counts, and the fetch pipeline refuses any request that would
push a day past its budget. Failed requests still count — assume Bloomberg
metered the attempt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Sequence


class LedgerError(RuntimeError):
    """The usage ledger is unreadable — refuse to fetch rather than guess."""


@dataclass
class UsageLedger:
    """Unique-security + per-day request accounting, persisted as JSON."""

    path: Path
    #: security string -> ISO date first requested
    securities: dict[str, str] = field(default_factory=dict)
    #: ISO date -> number of requests sent that day
    requests: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "UsageLedger":
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        try:
            raw = json.loads(p.read_text())
            return cls(
                path=p,
                securities=dict(raw["securities"]),
                requests={k: int(v) for k, v in raw["requests"].items()},
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise LedgerError(f"corrupt usage ledger {p}: {exc}") from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"securities": self.securities, "requests": self.requests},
                indent=2,
                sort_keys=True,
            )
        )

    @property
    def known_count(self) -> int:
        return len(self.securities)

    def new_securities(self, secs: Sequence[str]) -> list[str]:
        return [s for s in secs if s not in self.securities]

    def new_on(self, on: date) -> int:
        iso = on.isoformat()
        return sum(1 for d in self.securities.values() if d == iso)

    def allowance(self, on: date, max_new_per_day: int) -> int:
        return max(0, max_new_per_day - self.new_on(on))

    def record(self, secs: Sequence[str], on: date) -> None:
        iso = on.isoformat()
        for s in secs:
            self.securities.setdefault(s, iso)
        self.requests[iso] = self.requests.get(iso, 0) + 1
        self.save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bloomberg_ledger.py -v`
Expected: 6 passed

- [ ] **Step 5: Lint, type-check, full suite**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean; 127 passed

- [ ] **Step 6: Commit**

```bash
git add src/btf/data/bloomberg tests/test_bloomberg_ledger.py
git commit -m "M6: UsageLedger - persistent Bloomberg request accounting with daily budget"
```

---

### Task 2: Session seam + stage-1 membership fetch (PIT S&P 500)

**Files:**
- Create: `src/btf/data/bloomberg/session.py` (protocol + errors ONLY — the real `BlpSession` arrives in Task 7)
- Create: `src/btf/data/bloomberg/fetch.py` (stage 1)
- Create: `tests/bloomberg_fixtures.py`
- Test: `tests/test_bloomberg_fetch.py`

**Interfaces:**
- Consumes: `UsageLedger` from Task 1 (`.new_securities/.allowance/.record`).
- Produces (used by Tasks 3, 4, 5, 7):
  - `session.SessionLike` (Protocol): `index_members(index_security: str, on: date) -> list[str]`, `daily_bars(securities: Sequence[str], start: date, end: date) -> dict[str, pd.DataFrame]`
  - `session.BloombergError(RuntimeError)`
  - `fetch.INDEX_SECURITY = "SPX Index"`, `fetch.BENCHMARK_SYMBOL = "SPX"`, `fetch.MEMBERSHIP_FILENAME = "spx_membership.parquet"`
  - `fetch.bloomberg_dir(cache_dir: str | Path) -> Path` (= `Path(cache_dir) / "bloomberg"`)
  - `fetch.month_ends(start: date, end: date) -> list[date]`
  - `fetch.member_symbol(member: str) -> str` (`"AAPL UW"` → `"AAPL"`)
  - `fetch.security_for(symbol: str) -> str` (`"AAPL"` → `"AAPL US Equity"`)
  - `fetch.fetch_membership(session, ledger, cache_dir, start, end, *, on, max_new_per_day=300) -> pd.DataFrame` — columns `snapshot` (Timestamp), `symbol` (str); writes the membership parquet
  - `fetch.write_universe_file(membership: pd.DataFrame, path: str | Path) -> list[str]`

- [ ] **Step 1: Write the shared fake + failing tests**

```python
# tests/bloomberg_fixtures.py
"""Offline stand-ins for the Bloomberg session (tests never import blpapi)."""
from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


def raw_bars(start: str, periods: int, seed: int = 0) -> pd.DataFrame:
    """A plausible raw daily OHLCV frame as the session would return it."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=periods)
    close = 100 + np.cumsum(rng.normal(0, 1, periods))
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": rng.integers(1e5, 1e6, periods).astype(float),
        },
        index=idx,
    )


class FakeSession:
    """SessionLike double: canned members per month-end, canned bars per security."""

    def __init__(
        self,
        members_by_month: Mapping[date, list[str]] | None = None,
        bars: Mapping[str, pd.DataFrame] | None = None,
    ) -> None:
        self.members_by_month = dict(members_by_month or {})
        self.bars = dict(bars or {})  # keyed by SECURITY string ("AAPL US Equity")
        self.calls: list[tuple] = []

    def index_members(self, index_security: str, on: date) -> list[str]:
        self.calls.append(("members", index_security, on))
        return list(self.members_by_month[on])

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        self.calls.append(("bars", tuple(securities), start, end))
        # Securities absent from self.bars simply return nothing (Bloomberg
        # securityError behaves the same from the caller's viewpoint).
        return {s: self.bars[s] for s in securities if s in self.bars}
```

```python
# tests/test_bloomberg_fetch.py
"""Stage-1 membership fetch: PIT monthly snapshots -> parquet + universe file."""
from datetime import date

import pandas as pd

from btf.data.bloomberg.fetch import (
    MEMBERSHIP_FILENAME,
    bloomberg_dir,
    fetch_membership,
    member_symbol,
    month_ends,
    security_for,
    write_universe_file,
)
from btf.data.bloomberg.ledger import UsageLedger
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bloomberg_fetch.py -v`
Expected: FAIL — `ImportError` (no `btf.data.bloomberg.fetch`)

- [ ] **Step 3: Implement session protocol + stage-1 fetch**

```python
# src/btf/data/bloomberg/session.py
"""Bloomberg session seam (M6 spec §4).

``SessionLike`` is what the fetch pipeline types against; tests inject a fake.
The real ``BlpSession`` (added with the CLI task) is the ONLY code in the repo
that imports ``blpapi`` — lazily, so the package is an optional dependency.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


class BloombergError(RuntimeError):
    """Bloomberg session/API failure with an actionable message."""


@runtime_checkable
class SessionLike(Protocol):
    """The two Bloomberg operations the M6 pipeline needs."""

    def index_members(self, index_security: str, on: date) -> list[str]:
        """Index members as of ``on`` (INDX_MWEIGHT_HIST with END_DATE_OVERRIDE)."""
        ...

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        """Raw daily OHLCV per security; securities with no data are absent."""
        ...
```

```python
# src/btf/data/bloomberg/fetch.py
"""Budgeted Bloomberg snapshot fetch (M6 spec D3-D5).

Stage 1 (this task): monthly PIT S&P 500 membership -> spx_membership.parquet
plus the plain-text universe file the phase-2 config consumes. The entire
membership history costs ONE unique security ("SPX Index").

Every stage consults the UsageLedger BEFORE sending anything, and records
conservatively BEFORE the request goes out (a failed request still counted —
assume Bloomberg metered the attempt).
"""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import pandas as pd

from btf.data.bloomberg.ledger import LedgerError, UsageLedger
from btf.data.bloomberg.session import SessionLike

INDEX_SECURITY = "SPX Index"
#: Framework symbol under which the benchmark's bars are cached.
BENCHMARK_SYMBOL = "SPX"
MEMBERSHIP_FILENAME = "spx_membership.parquet"


def bloomberg_dir(cache_dir: str | Path) -> Path:
    return Path(cache_dir) / "bloomberg"


def month_ends(start: date, end: date) -> list[date]:
    """Calendar month-end dates in ``[start, end]`` (membership snapshot dates)."""
    out: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        me = date(y, m, calendar.monthrange(y, m)[1])
        if start <= me <= end:
            out.append(me)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def member_symbol(member: str) -> str:
    """``"AAPL UW"`` -> ``"AAPL"`` — drop Bloomberg's exchange code."""
    return member.split()[0]


def security_for(symbol: str) -> str:
    """Framework symbol -> Bloomberg security string."""
    return f"{symbol} US Equity"


def fetch_membership(
    session: SessionLike,
    ledger: UsageLedger,
    cache_dir: str | Path,
    start: date,
    end: date,
    *,
    on: date,
    max_new_per_day: int = 300,
) -> pd.DataFrame:
    """Monthly PIT membership snapshots -> DataFrame(snapshot, symbol) + parquet."""
    if ledger.new_securities([INDEX_SECURITY]) and ledger.allowance(on, max_new_per_day) < 1:
        raise LedgerError(f"daily budget exhausted ({max_new_per_day} new securities)")
    # Record before requesting (conservative: a crash mid-loop still counted).
    ledger.record([INDEX_SECURITY], on)
    rows: list[tuple[pd.Timestamp, str]] = []
    for me in month_ends(start, end):
        for member in session.index_members(INDEX_SECURITY, me):
            rows.append((pd.Timestamp(me), member_symbol(member)))
    frame = pd.DataFrame(rows, columns=["snapshot", "symbol"]).drop_duplicates()
    bdir = bloomberg_dir(cache_dir)
    bdir.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(bdir / MEMBERSHIP_FILENAME)
    return frame


def write_universe_file(membership: pd.DataFrame, path: str | Path) -> list[str]:
    """All-members-ever, sorted — the engine's iterated symbol set (config universe.file)."""
    symbols = sorted(set(membership["symbol"]))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Point-in-time S&P 500 members (all-ever over the snapshot window).\n"
        "# Generated by scripts/fetch_bloomberg_snapshot.py -- do not edit by hand.\n"
    )
    p.write_text(header + "\n".join(symbols) + "\n")
    return symbols
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bloomberg_fetch.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint, type-check, full suite**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green

- [ ] **Step 6: Commit**

```bash
git add src/btf/data/bloomberg tests/bloomberg_fixtures.py tests/test_bloomberg_fetch.py
git commit -m "M6: session seam + stage-1 PIT membership fetch (1 unique security)"
```

---

### Task 3: Stage-2 bars fetch — dry-run plan, budget gate, resume, failures

**Files:**
- Modify: `src/btf/data/bloomberg/fetch.py` (append)
- Test: `tests/test_bloomberg_fetch.py` (append)

**Interfaces:**
- Consumes: Task 1 ledger; Task 2 `SessionLike`, `bloomberg_dir`, `MEMBERSHIP_FILENAME`, `security_for`, `BENCHMARK_SYMBOL`; existing `btf.data._cache.cache_path/read_cache/write_cache`, `btf.data._normalize.normalize_ohlcv`.
- Produces (used by Task 7 CLI):
  - `fetch.FAILURES_FILENAME = "fetch_failures.json"`
  - `@dataclass BarsPlan(members: int, cached: int, failed: int, todo: int, allowed_today: int)` — `.todo` = uncached, non-failed symbols remaining; `.allowed_today` = min(todo, ledger allowance)
  - `fetch.plan_bars(ledger, cache_dir, start, end, *, on, max_new_per_day=300) -> BarsPlan` — **pure read, zero session use**
  - `@dataclass BarsResult(fetched: list[str], failed: dict[str, str], budget_stopped: bool, remaining: int)`
  - `fetch.fetch_bars(session, ledger, cache_dir, start, end, *, on, max_new_per_day=300, batch_size=50) -> BarsResult`
  - `fetch.fetch_benchmark(session, ledger, cache_dir, start, end, *, on) -> None` — SPX index bars cached under symbol `"SPX"`

- [ ] **Step 1: Write the failing tests (append to `tests/test_bloomberg_fetch.py`)**

```python
import json

from btf.data._cache import cache_path, read_cache
from btf.data.bloomberg.fetch import (
    BENCHMARK_SYMBOL,
    FAILURES_FILENAME,
    fetch_bars,
    fetch_benchmark,
    plan_bars,
)
from tests.bloomberg_fixtures import raw_bars

START, END = date(2020, 1, 15), date(2020, 3, 10)


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


def test_fetch_benchmark_caches_spx_bars(tmp_path):
    ledger = UsageLedger.load(tmp_path / "ledger.json")
    session = FakeSession(bars={INDEX_SECURITY: raw_bars("2020-01-15", 30)})
    fetch_benchmark(session, ledger, tmp_path, START, END, on=TODAY)
    cached = read_cache(cache_path(tmp_path, "bloomberg", BENCHMARK_SYMBOL, START, END, True))
    assert cached is not None and not cached.empty
```

Also add `INDEX_SECURITY` to the existing import from `btf.data.bloomberg.fetch` at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bloomberg_fetch.py -v`
Expected: new tests FAIL — `ImportError: cannot import name 'plan_bars'`

- [ ] **Step 3: Implement (append to `src/btf/data/bloomberg/fetch.py`)**

```python
# --- stage 2: daily bars (budget-gated, resumable) ---------------------------
import json  # noqa: E402  (move to the top import block)
from dataclasses import dataclass  # (move to the top import block)
from typing import Sequence  # (move to the top import block)

from btf.data._cache import cache_path, write_cache  # (top import block)
from btf.data._normalize import normalize_ohlcv  # (top import block)

FAILURES_FILENAME = "fetch_failures.json"


def _load_failures(bdir: Path) -> dict[str, str]:
    p = bdir / FAILURES_FILENAME
    return json.loads(p.read_text()) if p.exists() else {}


def _save_failures(bdir: Path, failures: dict[str, str]) -> None:
    (bdir / FAILURES_FILENAME).write_text(json.dumps(failures, indent=2, sort_keys=True))


def _member_symbols(cache_dir: str | Path) -> list[str]:
    m = pd.read_parquet(bloomberg_dir(cache_dir) / MEMBERSHIP_FILENAME)
    return sorted(set(m["symbol"]))


def _todo_symbols(
    cache_dir: str | Path, start: date, end: date, failures: dict[str, str]
) -> tuple[list[str], int]:
    """(uncached+unfailed symbols, cached count) for the snapshot window."""
    symbols = _member_symbols(cache_dir)
    cached = [
        s for s in symbols if cache_path(cache_dir, "bloomberg", s, start, end, True).exists()
    ]
    todo = [s for s in symbols if s not in set(cached) and s not in failures]
    return todo, len(cached)


@dataclass(frozen=True)
class BarsPlan:
    """Dry-run consumption estimate (spec D5) — computed with zero API calls."""

    members: int
    cached: int
    failed: int
    todo: int
    allowed_today: int


def plan_bars(
    ledger: UsageLedger,
    cache_dir: str | Path,
    start: date,
    end: date,
    *,
    on: date,
    max_new_per_day: int = 300,
) -> BarsPlan:
    failures = _load_failures(bloomberg_dir(cache_dir))
    todo, cached = _todo_symbols(cache_dir, start, end, failures)
    return BarsPlan(
        members=len(_member_symbols(cache_dir)),
        cached=cached,
        failed=len(failures),
        todo=len(todo),
        allowed_today=min(len(todo), ledger.allowance(on, max_new_per_day)),
    )


@dataclass
class BarsResult:
    fetched: list[str]
    failed: dict[str, str]
    budget_stopped: bool
    remaining: int


def fetch_bars(
    session: SessionLike,
    ledger: UsageLedger,
    cache_dir: str | Path,
    start: date,
    end: date,
    *,
    on: date,
    max_new_per_day: int = 300,
    batch_size: int = 50,
) -> BarsResult:
    """Fetch uncached member bars, hard-stopping BEFORE the daily budget is hit."""
    bdir = bloomberg_dir(cache_dir)
    failures = _load_failures(bdir)
    todo, _ = _todo_symbols(cache_dir, start, end, failures)
    fetched: list[str] = []
    new_failed: dict[str, str] = {}
    budget_stopped = False
    i = 0
    while i < len(todo):
        batch = todo[i : i + batch_size]
        secs = [security_for(s) for s in batch]
        # Budget gate BEFORE the request: trim to today's remaining allowance.
        allowance = ledger.allowance(on, max_new_per_day)
        n_new = len(ledger.new_securities(secs))
        if n_new > allowance:
            keep = 0
            new_seen = 0
            for s in secs:  # keep the longest prefix that fits the allowance
                new_seen += 1 if ledger.new_securities([s]) else 0
                if new_seen > allowance:
                    break
                keep += 1
            batch, secs = batch[:keep], secs[:keep]
            budget_stopped = True
            if not batch:
                break
        ledger.record(secs, on)  # count first — a failed request still counted
        frames = session.daily_bars(secs, start, end)
        for sym, sec in zip(batch, secs):
            raw = frames.get(sec)
            if raw is None or len(raw) == 0:
                new_failed[sym] = "no data"
                continue
            frame = normalize_ohlcv(raw)
            write_cache(cache_path(cache_dir, "bloomberg", sym, start, end, True), frame)
            fetched.append(sym)
        if budget_stopped:
            break
        i += batch_size
    if new_failed:
        _save_failures(bdir, {**failures, **new_failed})
    remaining = len(todo) - len(fetched) - len(new_failed)
    return BarsResult(fetched, new_failed, budget_stopped, remaining)


def fetch_benchmark(
    session: SessionLike,
    ledger: UsageLedger,
    cache_dir: str | Path,
    start: date,
    end: date,
    *,
    on: date,
) -> None:
    """Cache SPX index daily bars under the framework symbol ``"SPX"``."""
    path = cache_path(cache_dir, "bloomberg", BENCHMARK_SYMBOL, start, end, True)
    if path.exists():
        return
    ledger.record([INDEX_SECURITY], on)  # no-op on unique count if stage 1 ran
    frames = session.daily_bars([INDEX_SECURITY], start, end)
    raw = frames.get(INDEX_SECURITY)
    if raw is None or len(raw) == 0:
        raise LedgerError(f"no bars returned for {INDEX_SECURITY}")
    write_cache(path, normalize_ohlcv(raw))
```

(Consolidate the `import` lines into the module's top import block — the inline comments mark which ones.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bloomberg_fetch.py -v`
Expected: 10 passed

- [ ] **Step 5: Lint, type-check, full suite**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green

- [ ] **Step 6: Commit**

```bash
git add src/btf/data/bloomberg/fetch.py tests/test_bloomberg_fetch.py
git commit -m "M6: stage-2 budgeted bars fetch - dry-run plan, hard stop, resume, failures"
```

---

### Task 4: BloombergSnapshotProvider — offline DataProvider with PIT universe

**Files:**
- Create: `src/btf/data/bloomberg/snapshot_provider.py`
- Modify: `src/btf/data/bloomberg/__init__.py` (export)
- Test: `tests/test_bloomberg_provider.py`

**Interfaces:**
- Consumes: membership parquet + bar caches written by Tasks 2–3; `InMemoryDataProvider` (`btf.data.memory_provider`) for shape delegation; `read_cache`/`cache_path`.
- Produces (used by Tasks 6, 7):
  - `class SnapshotError(RuntimeError)`
  - `class BloombergSnapshotProvider` — implements `DataProvider`; ctor `(symbols: Sequence[str], start: date, end: date, *, cache_dir: str | Path, benchmark_symbol: str = "SPX", strict: bool = False)`; attribute `missing_symbols: list[str]`; `universe(on)` returns PIT members (latest monthly snapshot ≤ `on`, `[]` before the first snapshot). **Never fetches** — missing membership parquet raises `SnapshotError` naming the fetch command; missing bar files are collected into `missing_symbols` (raise only if `strict=True`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_bloomberg_provider.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bloomberg_provider.py -v`
Expected: FAIL — `ImportError: cannot import name 'BloombergSnapshotProvider'`

- [ ] **Step 3: Implement**

```python
# src/btf/data/bloomberg/snapshot_provider.py
"""Offline DataProvider over the Bloomberg parquet snapshot (M6 spec D2/D3).

Reads ONLY what the fetch script cached — a cache miss raises with the fetch
command instead of silently going to the network, so a backtest can never
consume Bloomberg quota. ``universe(on)`` is point-in-time: the members at the
latest monthly snapshot <= ``on`` (delisted included), which the engine hands
to strategies each bar (basic_engine passes ``data.universe(t)`` into the
context). Shape contracts delegate to InMemoryDataProvider, same as the
Phase-1 adapters.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

from btf.data._cache import cache_path, read_cache
from btf.data.bloomberg.fetch import MEMBERSHIP_FILENAME, bloomberg_dir
from btf.data.memory_provider import InMemoryDataProvider

_OHLCV = ("open", "high", "low", "close", "volume")
_FETCH_HINT = "run: python scripts/fetch_bloomberg_snapshot.py --stage {stage} --confirm"


class SnapshotError(RuntimeError):
    """The offline snapshot is incomplete — message names the fetch command."""


class BloombergSnapshotProvider:
    """Serves cached Bloomberg bars + PIT S&P 500 universe; never fetches."""

    source = "bloomberg"

    def __init__(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        *,
        cache_dir: str | Path,
        benchmark_symbol: str = "SPX",
        strict: bool = False,
    ) -> None:
        self.start, self.end = start, end
        mpath = bloomberg_dir(cache_dir) / MEMBERSHIP_FILENAME
        if not mpath.exists():
            raise SnapshotError(
                f"membership snapshot missing: {mpath}\n"
                + _FETCH_HINT.format(stage="membership")
            )
        m = pd.read_parquet(mpath)
        self._members: dict[pd.Timestamp, list[str]] = {
            ts: grp["symbol"].tolist() for ts, grp in m.groupby("snapshot")
        }
        self._snapshot_dates: list[pd.Timestamp] = sorted(self._members)

        bars: dict[str, pd.DataFrame] = {}
        missing: list[str] = []
        for sym in symbols:
            frame = read_cache(cache_path(cache_dir, "bloomberg", sym, start, end, True))
            if frame is None or frame.empty:
                missing.append(sym)
            else:
                bars[sym] = frame
        if missing and strict:
            raise SnapshotError(
                f"{len(missing)} symbol(s) missing cached bars "
                f"(e.g. {missing[:5]})\n" + _FETCH_HINT.format(stage="bars")
            )
        #: Symbols requested but not on disk — surfaced as coverage stats (D10).
        self.missing_symbols: list[str] = missing

        benchmark: pd.Series | None = None
        bframe = read_cache(
            cache_path(cache_dir, "bloomberg", benchmark_symbol, start, end, True)
        )
        if bframe is not None and not bframe.empty:
            benchmark = bframe["close"].rename(benchmark_symbol)
        self._inner = InMemoryDataProvider(
            bars, universe_symbols=list(symbols), benchmark=benchmark
        )

    # ---- point-in-time universe (the M6 point) --------------------------------

    def universe(self, on: date) -> list[str]:
        ts = pd.Timestamp(on)
        past = [d for d in self._snapshot_dates if d <= ts]
        return list(self._members[past[-1]]) if past else []

    # ---- DataProvider delegation ----------------------------------------------

    def trading_calendar(self, start: date, end: date) -> list[date]:
        return self._inner.trading_calendar(start, end)

    def history(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        fields: Sequence[str] = _OHLCV,
    ) -> pd.DataFrame:
        return self._inner.history(symbols, start, end, fields)

    def industry(self, symbol: str, on: date) -> str | None:
        return None  # deferred (spec D9) — zero extra unique-security cost later

    def earnings_dates(self, symbol: str) -> list[date]:
        return []  # deferred (spec D9)

    def index(self, name: str, start: date, end: date) -> pd.Series:
        return self._inner.index(name, start, end)
```

```python
# src/btf/data/bloomberg/__init__.py  (replace content)
"""Bloomberg Phase-2 data package (M6): offline snapshot provider + budgeted fetch."""
from btf.data.bloomberg.snapshot_provider import BloombergSnapshotProvider, SnapshotError

__all__ = ["BloombergSnapshotProvider", "SnapshotError"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bloomberg_provider.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint, type-check, full suite**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green

- [ ] **Step 6: Commit**

```bash
git add src/btf/data/bloomberg tests/test_bloomberg_provider.py
git commit -m "M6: BloombergSnapshotProvider - offline reads, PIT universe, coverage list"
```

---

### Task 5: VCP dynamic-universe exit fix

With a static Phase-1 universe, `positions ⊆ universe` always held. With a PIT universe, a held stock can LEAVE the index — today's `on_bar` loops only `ctx.universe`, so that position's trailing exit would never be evaluated again (only its resting hard stop and final liquidation would save it). Manage held positions regardless of membership.

**Files:**
- Modify: `src/btf/strategies/vcp.py:187-202` (`on_bar`)
- Test: `tests/test_vcp.py` (append)

**Interfaces:**
- Consumes: `Context.universe`, `Context.positions` (existing frozen contract).
- Produces: no signature change; behavioral guarantee "held symbols outside `ctx.universe` still get exit evaluation".

- [ ] **Step 1: Write the failing test (append to `tests/test_vcp.py`)**

Follow the file's existing fixture style for building a context — reuse its helpers if present. If the file builds contexts via `InMemoryDataProvider` + `BacktestContext`, mirror the closest existing exit test and shrink the universe; the essential shape:

```python
def test_exit_still_evaluated_when_symbol_leaves_universe():
    """PIT universe (M6): a held stock that leaves the index must still be managed."""
    # Arrange: same data/context as the existing trail-exit test, but with the
    # held symbol REMOVED from ctx.universe (simulate index deletion) while a
    # position in it is open and its close sits below the trail MA.
    ctx = _ctx_with_position_below_trail(universe=[])  # helper mirroring existing tests
    strat = VcpStrategy()
    signals = strat.on_bar(ctx)
    assert any(
        s.kind is SignalKind.EXIT and s.symbol == HELD_SYMBOL for s in signals
    )
```

(Write `_ctx_with_position_below_trail` by copying the arrangement of the file's existing trailing-exit test — same bars, same position construction — with the universe parameterized. Keep it in the test file.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vcp.py -k leaves_universe -v`
Expected: FAIL — no exit signal produced (symbol never visited)

- [ ] **Step 3: Implement the fix in `on_bar`**

```python
    def on_bar(self, ctx: Context) -> list[Signal]:
        signals: list[Signal] = []
        rs = self._rs_percentiles(ctx)
        universe = list(ctx.universe)
        # PIT universe (M6): a held stock may have left the index — keep
        # managing its exit; only NEW entries are restricted to members.
        held_outside = [s for s in ctx.positions if s not in set(universe)]
        for sym in [*universe, *held_outside]:
            df = ctx.history(sym)
            if len(df) == 0:
                continue
            if sym in ctx.positions:
                exit_sig = self._exit_signal(sym, df)
                if exit_sig is not None:
                    signals.append(exit_sig)
                continue
            entry_sig = self._entry_signal(sym, df, rs)
            if entry_sig is not None:
                signals.append(entry_sig)
        return signals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vcp.py -v`
Expected: all pass (existing VCP tests unchanged — with a static universe, `held_outside` is always empty)

- [ ] **Step 5: Lint, type-check, full suite**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green

- [ ] **Step 6: Commit**

```bash
git add src/btf/strategies/vcp.py tests/test_vcp.py
git commit -m "M6: VCP manages exits for held stocks that leave the PIT universe"
```

---

### Task 6: Config plumbing — `universe.file`, provider registry, phase-2 YAML

**Files:**
- Modify: `src/btf/config/loader.py` (universe section + `load_config` base dir)
- Modify: `src/btf/config/builder.py` (register `"bloomberg"`)
- Create: `config/vcp_phase2_bloomberg.yaml`
- Test: `tests/test_config.py` (append)

**Interfaces:**
- Consumes: `BloombergSnapshotProvider` (Task 4).
- Produces:
  - `config_from_dict(d, base_dir: str | Path | None = None)` — `universe:` now takes **exactly one** of `symbols: [..]` or `file: <path>` (relative paths resolve against `base_dir`; one symbol per line, `#` comments and blanks ignored).
  - `PROVIDERS["bloomberg"]` → `BloombergSnapshotProvider(list(cfg.symbols), cfg.start, cfg.end, cache_dir=cfg.data.cache_dir, benchmark_symbol=cfg.data.benchmark or "SPX")`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_config.py`, following its existing style)**

```python
def test_universe_file_loads_symbols(tmp_path):
    (tmp_path / "u.txt").write_text("# generated\nAAA\n\nBBB\n")
    d = _minimal_config_dict()          # reuse/extend the file's existing helper
    d["universe"] = {"file": "u.txt"}
    cfg = config_from_dict(d, base_dir=tmp_path)
    assert cfg.symbols == ("AAA", "BBB")


def test_universe_requires_exactly_one_of_symbols_or_file(tmp_path):
    d = _minimal_config_dict()
    d["universe"] = {}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)
    d["universe"] = {"symbols": ["AAA"], "file": "u.txt"}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)


def test_universe_file_missing_or_empty_fails_loudly(tmp_path):
    d = _minimal_config_dict()
    d["universe"] = {"file": "absent.txt"}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)
    (tmp_path / "empty.txt").write_text("# only comments\n")
    d["universe"] = {"file": "empty.txt"}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)


def test_bloomberg_provider_registered():
    from btf.config.builder import PROVIDERS
    assert "bloomberg" in PROVIDERS
```

(If `tests/test_config.py` has no `_minimal_config_dict` helper, add one returning the smallest valid dict: `name`, `period`, `universe`, `strategy` — copy shapes from the file's existing tests.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: new tests FAIL (`unknown key(s) in universe: ['file']`, missing registry key)

- [ ] **Step 3: Implement**

In `src/btf/config/loader.py`:

```python
def load_config(path: str | Path) -> RunConfig:
    """Parse a YAML file into a validated ``RunConfig``."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(raw).__name__}")
    return config_from_dict(raw, base_dir=Path(path).parent)


def config_from_dict(d: Mapping[str, Any], base_dir: str | Path | None = None) -> RunConfig:
    ...
    universe = _require(d, "universe", Mapping)
    _reject_unknown(universe, {"symbols", "file"}, where="universe")
    symbols = _universe_symbols(universe, base_dir)
    ...
```

and replace the old inline symbols block with:

```python
def _universe_symbols(universe: Mapping[str, Any], base_dir: str | Path | None) -> list[str]:
    """Exactly one of ``symbols`` (inline) or ``file`` (one symbol per line)."""
    has_symbols = universe.get("symbols") is not None
    has_file = universe.get("file") is not None
    if has_symbols == has_file:
        raise ConfigError("universe: provide exactly one of 'symbols' or 'file'")
    if has_symbols:
        symbols = universe["symbols"]
        if not isinstance(symbols, list) or not symbols or not all(
            isinstance(s, str) for s in symbols
        ):
            raise ConfigError("universe.symbols must be a non-empty list of strings")
        return list(symbols)
    fpath = Path(universe["file"])
    if not fpath.is_absolute() and base_dir is not None:
        fpath = Path(base_dir) / fpath
    if not fpath.exists():
        raise ConfigError(f"universe.file not found: {fpath}")
    symbols = [
        ln.strip()
        for ln in fpath.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not symbols:
        raise ConfigError(f"universe.file has no symbols: {fpath}")
    return symbols
```

In `src/btf/config/builder.py`, next to the other provider factories:

```python
def _bloomberg_provider(cfg: RunConfig) -> DataProvider:
    from btf.data.bloomberg import BloombergSnapshotProvider

    return BloombergSnapshotProvider(
        list(cfg.symbols), cfg.start, cfg.end,
        cache_dir=cfg.data.cache_dir,
        benchmark_symbol=cfg.data.benchmark or "SPX",
    )


PROVIDERS: dict[str, Callable[[RunConfig], DataProvider]] = {
    "yfinance": _yfinance_provider,
    "stooq": _stooq_provider,
    "bloomberg": _bloomberg_provider,
}
```

Create `config/vcp_phase2_bloomberg.yaml`:

```yaml
# Phase-2 credible run (M6): survivorship-free PIT S&P 500 via the Bloomberg
# snapshot. Requires the snapshot on disk first:
#
#   python scripts/fetch_bloomberg_snapshot.py --stage membership --confirm
#   python scripts/fetch_bloomberg_snapshot.py --stage bars --confirm   # repeat daily until done
#   python scripts/run_config.py config/vcp_phase2_bloomberg.yaml --validate
#
# Membership granularity is monthly (spec D3); coverage gaps are printed, not hidden.

name: vcp-phase2-spx-pit

period:
  start: 2010-01-01
  end: 2025-12-31

universe:
  file: universe_spx_2010_2025.txt   # generated by the fetch script (stage membership)

data:
  source: bloomberg
  cache_dir: data_cache
  benchmark: SPX

costs:
  commission_per_share: 0.005
  slippage_pct: 0.0005

risk:
  risk_pct: 0.01
  starting_cash: 100000

strategy:
  name: vcp
  params: {}              # same brain-derived defaults as Phase 1 (comparable results)

validation:
  oos_start: 2021-01-01           # tune on 2010-20; 2021-25 spent once
  walk_forward_windows: 5         # ~3y each, well past VCP warmup
  sensitivity:                    # one-at-a-time around the baseline (same axes as Phase 1)
    tight_window: [6, 8, 10, 12, 14]
    rs_min_percentile: [0.60, 0.70, 0.80]
    stop_atr_mult: [0.5, 1.0, 1.5]
    trail_ma: [20, 50]
    vol_expansion: [1.1, 1.3, 1.5]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: all pass

- [ ] **Step 5: Lint, type-check, full suite**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green

- [ ] **Step 6: Commit**

```bash
git add src/btf/config config/vcp_phase2_bloomberg.yaml tests/test_config.py
git commit -m "M6: universe.file config support + bloomberg provider registry + phase-2 YAML"
```

---

### Task 7: Real `BlpSession` + fetch CLI + phase-aware report footer

**Files:**
- Modify: `src/btf/data/bloomberg/session.py` (append `BlpSession`)
- Create: `scripts/fetch_bloomberg_snapshot.py`
- Modify: `scripts/run_config.py:72-74` (conditional bias footer)
- Modify: `pyproject.toml` (optional dep group + mypy override)

**Interfaces:**
- Consumes: everything from Tasks 1–4, 6.
- Produces: `BlpSession(host="localhost", port=8194)` implementing `SessionLike`, plus `.close()`. CLI: `python scripts/fetch_bloomberg_snapshot.py --stage {membership,bars} [--confirm] [--max-new-per-day 300] [--cache-dir data_cache] [--start 2010-01-01] [--end 2025-12-31] [--universe-out config/universe_spx_2010_2025.txt]`. Default (no `--confirm`) is dry-run.

`BlpSession` is deliberately excluded from unit tests (real API; verified manually in Task 8's runbook). Keep it thin — no logic beyond request/response marshalling.

- [ ] **Step 1: Append `BlpSession` to `session.py`**

```python
_PX_FIELDS = {
    "PX_OPEN": "open",
    "PX_HIGH": "high",
    "PX_LOW": "low",
    "PX_LAST": "close",
    "PX_VOLUME": "volume",
}
_INSTALL_HINT = (
    "blpapi is not installed. Run:\n"
    "  pip install blpapi --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/"
)
_CONNECT_HINT = (
    "cannot reach the Bloomberg Desktop API on {host}:{port} — "
    "make sure the Terminal is running and you are logged in, then retry"
)


class BlpSession:
    """Real Desktop-API session (implements SessionLike). The ONLY blpapi user."""

    def __init__(self, host: str = "localhost", port: int = 8194) -> None:
        try:
            import blpapi
        except ImportError as exc:  # pragma: no cover - needs Bloomberg install
            raise BloombergError(_INSTALL_HINT) from exc
        self._blpapi = blpapi
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        self._session = blpapi.Session(opts)
        if not self._session.start() or not self._session.openService("//blp/refdata"):
            raise BloombergError(_CONNECT_HINT.format(host=host, port=port))
        self._svc = self._session.getService("//blp/refdata")

    def close(self) -> None:
        self._session.stop()

    # -- SessionLike -----------------------------------------------------------

    def index_members(self, index_security: str, on: date) -> list[str]:
        req = self._svc.createRequest("ReferenceDataRequest")
        req.getElement("securities").appendValue(index_security)
        req.getElement("fields").appendValue("INDX_MWEIGHT_HIST")
        override = req.getElement("overrides").appendElement()
        override.setElement("fieldId", "END_DATE_OVERRIDE")
        override.setElement("value", on.strftime("%Y%m%d"))
        members: list[str] = []
        for msg in self._responses(req):
            sdata = msg.getElement("securityData")
            for i in range(sdata.numValues()):
                fdata = sdata.getValueAsElement(i).getElement("fieldData")
                if not fdata.hasElement("INDX_MWEIGHT_HIST"):
                    continue
                hist = fdata.getElement("INDX_MWEIGHT_HIST")
                for j in range(hist.numValues()):
                    members.append(
                        hist.getValueAsElement(j).getElementAsString("Index Member")
                    )
        return members

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        req = self._svc.createRequest("HistoricalDataRequest")
        for sec in securities:
            req.getElement("securities").appendValue(sec)
        for f in _PX_FIELDS:
            req.getElement("fields").appendValue(f)
        req.set("startDate", start.strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        req.set("periodicitySelection", "DAILY")
        # Split + normal-dividend adjusted, matching Phase-1 yfinance auto_adjust (D6).
        req.set("adjustmentSplit", True)
        req.set("adjustmentNormal", True)
        req.set("adjustmentAbnormal", False)
        out: dict[str, pd.DataFrame] = {}
        for msg in self._responses(req):
            sdata = msg.getElement("securityData")
            sec = sdata.getElementAsString("security")
            if sdata.hasElement("securityError"):
                continue  # recorded as a failure by the caller
            fdata = sdata.getElement("fieldData")
            rows = []
            for i in range(fdata.numValues()):
                e = fdata.getValueAsElement(i)
                if not all(e.hasElement(f) for f in _PX_FIELDS):
                    continue
                row = {name: e.getElementAsFloat(f) for f, name in _PX_FIELDS.items()}
                row["date"] = e.getElementAsDatetime("date")
                rows.append(row)
            if rows:
                out[sec] = pd.DataFrame(rows).set_index("date")
        return out

    def _responses(self, req):  # type: ignore[no-untyped-def]  # blpapi is untyped
        self._session.sendRequest(req)
        while True:
            event = self._session.nextEvent(30_000)
            if event.eventType() in (
                self._blpapi.Event.RESPONSE,
                self._blpapi.Event.PARTIAL_RESPONSE,
            ):
                for msg in event:
                    if msg.hasElement("responseError"):
                        raise BloombergError(str(msg.getElement("responseError")))
                    yield msg
            if event.eventType() == self._blpapi.Event.RESPONSE:
                return
```

- [ ] **Step 2: Write the CLI**

```python
#!/usr/bin/env python3
# scripts/fetch_bloomberg_snapshot.py
"""Budgeted Bloomberg snapshot fetch (M6). DRY-RUN BY DEFAULT — nothing is
requested without --confirm, and a hard daily budget (--max-new-per-day)
stops the run BEFORE Bloomberg's opaque unique-security cap is at risk.

Two stages (spec D5):

    python scripts/fetch_bloomberg_snapshot.py --stage membership            # plan
    python scripts/fetch_bloomberg_snapshot.py --stage membership --confirm  # ~1 unique security
    python scripts/fetch_bloomberg_snapshot.py --stage bars                  # exact plan
    python scripts/fetch_bloomberg_snapshot.py --stage bars --confirm        # repeat daily until done

Requires the Bloomberg Terminal running + logged in on this machine, and:
    pip install blpapi --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/
"""
from __future__ import annotations

import argparse
from datetime import date

from btf.data.bloomberg import fetch
from btf.data.bloomberg.ledger import UsageLedger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["membership", "bars"], required=True)
    parser.add_argument("--confirm", action="store_true",
                        help="actually fetch (default: dry-run plan only)")
    parser.add_argument("--max-new-per-day", type=int, default=300)
    parser.add_argument("--cache-dir", default="data_cache")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2010, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument("--universe-out", default="config/universe_spx_2010_2025.txt")
    args = parser.parse_args()
    today = date.today()

    ledger = UsageLedger.load(fetch.bloomberg_dir(args.cache_dir) / "usage_ledger.json")
    print(f"ledger: {ledger.known_count} unique securities ever, "
          f"{ledger.new_on(today)} new today, "
          f"allowance today = {ledger.allowance(today, args.max_new_per_day)}")

    if args.stage == "membership":
        months = fetch.month_ends(args.start, args.end)
        print(f"membership plan: {len(months)} monthly snapshots of {fetch.INDEX_SECURITY} "
              f"= 1 unique security, ~{len(months) + 1} requests (incl. SPX bars)")
        if not args.confirm:
            print("dry-run only. Re-run with --confirm to fetch.")
            return 0
        from btf.data.bloomberg.session import BlpSession
        session = BlpSession()
        try:
            m = fetch.fetch_membership(session, ledger, args.cache_dir,
                                       args.start, args.end, on=today,
                                       max_new_per_day=args.max_new_per_day)
            fetch.fetch_benchmark(session, ledger, args.cache_dir,
                                  args.start, args.end, on=today)
        finally:
            session.close()
        symbols = fetch.write_universe_file(m, args.universe_out)
        per_month = m.groupby("snapshot")["symbol"].count()
        print(f"membership: {len(symbols)} distinct members over {len(per_month)} months "
              f"(min {per_month.min()}, max {per_month.max()} per month)")
        print(f"universe file written: {args.universe_out}")
        return 0

    # stage == "bars"
    plan = fetch.plan_bars(ledger, args.cache_dir, args.start, args.end,
                           on=today, max_new_per_day=args.max_new_per_day)
    print(f"bars plan: {plan.members} members | {plan.cached} cached | "
          f"{plan.failed} failed previously | {plan.todo} to fetch | "
          f"{plan.allowed_today} allowed today")
    if not args.confirm:
        print("dry-run only. Re-run with --confirm to fetch.")
        return 0
    from btf.data.bloomberg.session import BlpSession
    session = BlpSession()
    try:
        res = fetch.fetch_bars(session, ledger, args.cache_dir, args.start, args.end,
                               on=today, max_new_per_day=args.max_new_per_day)
    finally:
        session.close()
    print(f"fetched {len(res.fetched)}, failed {len(res.failed)}, "
          f"remaining {res.remaining}")
    if res.budget_stopped:
        print(f"daily budget ({args.max_new_per_day} new securities) reached — "
              f"re-run tomorrow to continue. Nothing exceeded the cap.")
    elif res.remaining == 0:
        print("snapshot complete. Next: "
              "python scripts/run_config.py config/vcp_phase2_bloomberg.yaml --validate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Make the run_config bias footer phase-aware**

Replace `scripts/run_config.py` lines 72–74 with:

```python
    if cfg.data.source == "bloomberg":
        missing = sorted(getattr(provider, "missing_symbols", []))
        print("\nData: Bloomberg snapshot — survivorship-free PIT S&P 500 universe "
              "(monthly membership granularity; see M6 spec).")
        if missing:
            head = ", ".join(missing[:15]) + (" ..." if len(missing) > 15 else "")
            print(f"[!] coverage: {len(missing)} member(s) without cached bars: {head}")
    else:
        print("\n[!] SELECTION / SURVIVORSHIP BIAS (Phase-1): hand-picked, currently-listed "
              "symbols; no delisted names. Expectancy is upward-biased until M6's "
              "survivorship-free data. See BACKTESTING_PLAN.md §6.")
```

- [ ] **Step 4: pyproject — optional dependency + mypy override**

In `pyproject.toml`: add `bloomberg = ["blpapi"]` to `[project.optional-dependencies]` (alongside the existing `data` extra), and:

```toml
[[tool.mypy.overrides]]
module = "blpapi"
ignore_missing_imports = true
```

- [ ] **Step 5: Verify — lint, types, full suite, CLI smoke (dry-run paths only)**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green (nothing imports blpapi at test time)

Run: `python scripts/fetch_bloomberg_snapshot.py --stage bars --cache-dir data_cache`
Expected: fails fast with the membership-missing `SnapshotError`? — NO: `plan_bars` reads the membership parquet, so expect `FileNotFoundError`-style message. Guard it: wrap the `plan_bars` call in the CLI with

```python
    try:
        plan = fetch.plan_bars(...)
    except FileNotFoundError:
        print("no membership snapshot yet — run --stage membership first")
        return 1
```

Re-run: expect exit 1 with that message (proves dry-run touches no network).

- [ ] **Step 6: Commit**

```bash
git add src/btf/data/bloomberg/session.py scripts/fetch_bloomberg_snapshot.py scripts/run_config.py pyproject.toml
git commit -m "M6: BlpSession + budgeted fetch CLI (dry-run default) + phase-aware bias footer"
```

---

### Task 8: Runbook — real pull (staged over days), credible report, docs, brain backfill

This task is **manual + gated by the Terminal being logged in**; everything else in the plan is offline. Do NOT parallelize with other tasks; do not exceed one `--confirm` bars run per calendar day.

**Files:**
- Modify: `README.md` (roadmap row M6 → done), `CLAUDE.md` (Status/next step), `BACKTESTING_PLAN.md` (Decision Log: Bloomberg replaces Norgate for Phase 2, user-owned Terminal)
- Create: `config/universe_spx_2010_2025.txt` (generated by stage 1 — commit it)
- Create: `docs/reports/` phase-2 report output if the repo convention emerges (otherwise console output pasted into the brain)
- Modify (sibling brain, per its CLAUDE.md workflows): `../wiki/setups/vcp-breakout.md` (Evidence), `../log.md` (backtest entry), `../index.md` if new pages

**Steps:**

- [ ] **Step 1: Install blpapi**

Run: `pip install blpapi --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/`
Expected: installs cleanly; `python -c "import blpapi"` OK. Terminal must be logged in.

- [ ] **Step 2: Stage 1 — membership (dry-run, then confirm)**

Run: `python scripts/fetch_bloomberg_snapshot.py --stage membership`
Expected: plan shows 192 monthly snapshots, 1 unique security.
Run with `--confirm`. Verify: ~500 members per month (min/max printed sane, 490–510 typical), `config/universe_spx_2010_2025.txt` written with ~900–1,100 symbols, ledger shows 1 unique security.

- [ ] **Step 3: Sanity-check membership against known history**

Spot-check 3 known index changes on the Terminal (e.g., TSLA joins 2020-12; a 2010-era delisted member such as EK/Eastman Kodak present early, absent later). If exchange-code stripping produced junk symbols (numbers, empty), fix `member_symbol` before proceeding.

- [ ] **Step 4: Stage 2 — bars, one budgeted run per day until complete**

Each day: dry-run first (`--stage bars`), review the printed plan, then `--stage bars --confirm`. Expected per day: ≤300 new securities fetched, `budget_stopped` message, clean resume next day. After the final day: "snapshot complete".
Verify a delisted member's parquet exists and its bars end near its delisting date (spot-check 2–3 on the Terminal).

- [ ] **Step 5: The credible run**

Run: `python scripts/run_config.py config/vcp_phase2_bloomberg.yaml --validate`
Expected: base-run metrics table + OOS split + walk-forward + sensitivity, the Bloomberg data-source footer with coverage stats, **no survivorship warning**. Save the full console output.

- [ ] **Step 6: Backfill the brain (sibling knowledge base workflows)**

Per the brain's backtest workflow: record instrument/timeframe/period/sample size, R-metrics, regime breakdown into `../wiki/setups/vcp-breakout.md` → Evidence (honest about coverage gaps + monthly membership granularity); append a `backtest` line to `../log.md`; update `../index.md` if pages were added.

- [ ] **Step 7: Docs + roadmap**

README roadmap: M6 row → ✅ with one-line summary. `code/CLAUDE.md` Status: M6 done, next M7. `BACKTESTING_PLAN.md` Decision Log: append the Bloomberg decision (user-owned Terminal, ledger-budgeted snapshot, Norgate remains a possible future adapter).

- [ ] **Step 8: Final verification + commit**

Run: `ruff check . && mypy src && python -m pytest -q`
Expected: clean, all green.

```bash
git add README.md CLAUDE.md BACKTESTING_PLAN.md config/universe_spx_2010_2025.txt
git commit -m "M6: credible phase-2 VCP report on Bloomberg PIT snapshot; docs + roadmap"
```

Then use superpowers:finishing-a-development-branch (merge/PR decision). Note: whether to commit `data_cache/bloomberg/*.parquet` (reproducibility) vs. keep it local (size, licensing) — **ask the human**; Bloomberg data is licensed to the Terminal owner and generally must NOT be pushed to a public repo. Recommend: keep parquet local, commit only the membership-derived `universe_spx_2010_2025.txt` + `usage_ledger.json` stays local too.

---

## Plan Self-Review (completed)

- **Spec coverage:** D1 (Task 8 docs) · D2 (Tasks 4, 7) · D3 (Tasks 2, 4) · D4 (Tasks 1, 3) · D5 (Tasks 3, 7) · D6 (Tasks 3, 7 — adjustment flags) · D7 (Task 3 full-window fetch + failures; spec amended) · D8 (Tasks 3, 4 benchmark) · D9 (Task 4 stubs) · D10 (Tasks 6, 7, 8 config/report/coverage). Acceptance 1→Tasks 3/7, 2→Task 8, 3→all test tasks, 4→every task's lint step.
- **Placeholders:** Task 5's test intentionally references the existing `tests/test_vcp.py` fixtures (implementer must mirror the file's real helpers — named there); no TBDs remain.
- **Type consistency:** `UsageLedger` API (`new_securities/new_on/allowance/record/known_count`) matches across Tasks 1/2/3/7; `SessionLike` two-method surface matches `FakeSession` and `BlpSession`; provider ctor matches the Task 6 registry call; `BENCHMARK_SYMBOL="SPX"` consistent with YAML `benchmark: SPX`.
