# M6 — Phase-2 Data: Bloomberg Snapshot Provider (Design Spec)

- **Date:** 2026-07-02
- **Milestone:** M6 (README roadmap: "Phase-2 data — survivorship-free provider, the 'credible' report")
- **Scope:** A survivorship-free data source behind the frozen `DataProvider` interface, fed by the
  user's **Bloomberg Terminal Desktop API** on this PC, plus the rerun of the VCP config + validation
  protocol on it — producing the first *credible* report and backfilling the brain's Evidence section.
- **Status:** Approved for implementation.
- **Depends on:** M5 (config-YAML runs + validation, merged).

> **Deviation from plan §3.3.** `BACKTESTING_PLAN.md` prefers **Norgate** for Phase 2. Norgate is not
> installed and costs ~US$630/yr; the user already has a Bloomberg Terminal **on this machine**
> (`C:\blp` present, DAPI port 8194 answering), so Phase 2 uses Bloomberg at zero incremental cost.
> The `DataProvider` abstraction is the whole point: a Norgate adapter can still be added later
> without touching engine or strategies.

> Domain reminder: for **studying and backtesting** only. Document and measure — never place live
> trades, move money, or give buy/sell recommendations.

---

## 1. Goal

Produce the first survivorship-free VCP backtest:

- **Universe:** point-in-time S&P 500 membership, **2010-01-01 → 2025-12-31**, delisted members
  included (~900–1,000 unique securities).
- **Source:** Bloomberg Desktop API (`blpapi`, localhost:8194), consumed **snapshot-first**: one
  budgeted fetch script pulls everything into the local parquet cache; backtests run fully offline.
- **Output:** `python scripts/run_config.py config/vcp_phase2_bloomberg.yaml --validate` runs the
  same VCP parameters as Phase 1 on the new snapshot and emits the credible report (survivorship
  warning replaced by a data-source statement + coverage stats).

**Acceptance:**
1. `fetch_bloomberg_snapshot.py --dry-run` prints planned consumption (new unique securities, est.
   requests) and makes **zero** API calls for anything not already budgeted-and-confirmed.
2. After the confirmed fetch completes (possibly across several days), the config run + validation
   protocol complete **without any live Bloomberg call**.
3. All existing tests stay green; new tests cover ledger, budget stop, and point-in-time universe
   invariants — the test suite never imports `blpapi`.
4. `ruff` + `mypy src` clean; `blpapi` remains an optional dependency (imported only inside the
   session module).

## 2. Non-negotiables

- **Never break the Bloomberg data cap.** Cap safety is *structural*: only the fetch script can
  reach `blpapi`; every request is pre-counted against a persistent ledger with a hard daily stop;
  nothing fetches without an explicit `--confirm`. (User constraint, this session.)
- **Strategy ⟂ Engine, vendor-blind.** Engine and strategies see only `DataProvider`. No Bloomberg
  type, field name, or ticker convention leaks past `btf/data/bloomberg/`.
- **No look-ahead.** `universe(on)` returns membership as of the latest snapshot **≤ on**; history
  and index reads are clipped to the requested range exactly as Phase-1 providers do.
- **Reproducibility.** Same parquet snapshot ⇒ same result. The snapshot directory is the pinned
  artifact (commit or archive it), matching the M2 cache philosophy.

## 3. Locked decisions

| # | Decision |
|---|----------|
| D1 | **Bloomberg DAPI, not Norgate** — user has a Terminal on this PC (see deviation note). |
| D2 | **Snapshot-first.** `scripts/fetch_bloomberg_snapshot.py` is the *only* code path that opens a blpapi session. `BloombergSnapshotProvider` reads parquet only; a cache miss raises (with the fetch command in the message) rather than fetching. |
| D3 | **Universe = PIT S&P 500, monthly.** Membership from `INDX_MWEIGHT_HIST` on `SPX Index` with month-end `END_DATE_OVERRIDE`, 2010–2025 (~192 requests against **one** unique security). `universe(on)` = members at the latest month-end ≤ `on`. Intramonth joins/leaves are approximated at monthly granularity — acceptable and stated in the report. |
| D4 | **Budget ledger.** `data_cache/bloomberg/usage_ledger.json` records (a) the set of unique securities ever requested (never re-counted), (b) per-calendar-day request/hit counts. Defaults: **max 300 new unique securities per day** (hard stop mid-run), configurable via `--max-new-per-day`. Full pull therefore spans ~3–4 days by design. Failed securities still count (assume Bloomberg metered the attempt). |
| D5 | **Two-stage fetch.** Stage 1: membership history (1 unique security, cheap) → distinct member list persisted to `spx_membership.parquet`. Stage 2: daily OHLCV per member, batched (~50 securities/request), resumable — already-cached symbols and ledger-known securities are skipped. `--dry-run` on stage 2 reads the membership file and prints the exact new-unique-security count before anything is confirmed. |
| D6 | **Fields & adjustment.** `PX_OPEN/PX_HIGH/PX_LOW/PX_LAST/PX_VOLUME`, split- **and** dividend-adjusted (DPDF), matching Phase-1 yfinance `auto_adjust` so Phase-1 vs Phase-2 results are comparable. Stored via the existing `_cache.cache_path(source="bloomberg", adjusted=True)` scheme after `_normalize`. |
| D7 | **Symbols.** Members are requested as `"<ticker> US Equity"`. Ticker recycling (a delisted ticker reused by a new listing) is a known residual risk — mitigated by requesting history only within the member's observed membership window and reporting per-symbol coverage; FIGI-based identity is deferred unless coverage stats show a real problem. |
| D8 | **Index/benchmark.** `index("SPX", ...)` serves SPX daily closes from the same snapshot (fetched in stage 1; 1 unique security), feeding the regime classifier and benchmark curve. |
| D9 | **`industry()` / `earnings_dates()` return empty** in M6 (nothing consumes them yet). Adding them later re-requests only already-counted securities — zero new unique-security cost. |
| D10 | **Config & report.** `config/vcp_phase2_bloomberg.yaml` = Phase-1 VCP params, new provider/universe/period. The report replaces the survivorship warning with: data source, universe definition, monthly-membership approximation note, and **coverage stats** (% member-days with bars; symbols with missing history listed). |

## 4. Components

```
src/btf/data/bloomberg/
  __init__.py            # exports BloombergSnapshotProvider
  session.py             # thin blpapi wrapper: connect, refdata requests, response iteration
                         #   (the ONLY module importing blpapi; import is lazy + guarded)
  ledger.py              # UsageLedger: load/save JSON, count(), would_exceed(), record()
  fetch.py               # stage-1 membership + stage-2 batched OHLCV; consults ledger BEFORE
                         #   every request; writes parquet via _cache/_normalize
  snapshot_provider.py   # BloombergSnapshotProvider(DataProvider): offline parquet reads,
                         #   PIT universe from spx_membership.parquet
scripts/fetch_bloomberg_snapshot.py   # CLI: stage selection, --dry-run (default), --confirm,
                                      #   --max-new-per-day, prints ledger status
config/vcp_phase2_bloomberg.yaml
tests/data/bloomberg/    # FakeSession fixtures; no blpapi import anywhere in tests
```

Each unit stands alone: `session` knows Bloomberg wire details but nothing about budgets; `ledger`
knows budgets but nothing about Bloomberg; `fetch` composes them; the provider knows only parquet.

## 5. Data flow

```
[stage 1]  fetch.py ──membership requests (SPX Index)──▶ spx_membership.parquet + SPX bars
[dry-run]  fetch.py ──reads membership + ledger──▶ "947 members, 812 new unique securities;
           daily budget allows 300 today (~6 batched requests) — rerun with --confirm to fetch"
[stage 2]  fetch.py ──batched OHLCV (ledger-gated, resumable)──▶ data_cache/bloomberg/*.parquet
[backtest] run_config.py ──BloombergSnapshotProvider (offline)──▶ engine ──▶ report + validation
```

## 6. Error handling

- **Session unavailable** (Terminal logged out / bbcomm down): clear actionable error before any
  budget is spent — "log into the Bloomberg Terminal and retry".
- **Per-security errors** (unknown/delisted-unresolvable): logged, recorded in the ledger and in a
  `fetch_report.json` (symbol → status), never retried automatically; surfaced as coverage stats.
- **Interrupt / budget stop mid-run:** everything fetched so far is cached; rerun resumes where it
  left off. The stop message states how many securities remain and when the daily budget resets.
- **Provider cache miss at backtest time:** raise with the exact fetch command — never a silent
  live call.

## 7. Testing

- **Ledger invariants:** hard stop actually stops *before* the over-budget request; re-requesting a
  known security adds zero new-unique count; persistence round-trips; corrupt ledger fails loudly.
- **Fetch logic against `FakeSession`:** batching, resume-skip of cached symbols, membership
  parsing, failure recording. `FakeSession` replays canned response structures.
- **Provider PIT invariants:** `universe(on)` never contains a member whose first membership
  snapshot is after `on`; `history`/`index` clipped to range; conforms to `DataProvider`
  (runtime_checkable) — mirroring existing provider tests.
- **Config round-trip:** `vcp_phase2_bloomberg.yaml` loads into `RunConfig` and resolves the new
  provider.
- **Manual verification (real pull, documented in the plan doc):** stage 1 → inspect membership
  counts against known S&P history (e.g., ~500 members every month); spot-check 2–3 delisted
  names' bars against the Terminal itself; then the confirmed staged stage-2 pull.

## 8. Risks / honest caveats

- **Bloomberg's meter is opaque.** The ledger counts *our* requests conservatively (worst case);
  the daily hard stop is the backstop if Bloomberg's accounting differs. Defaults are deliberately
  far below commonly-reported Terminal limits.
- **Ticker recycling** may map a dead ticker to a new company's history (D7 mitigation + coverage
  reporting; FIGI upgrade path if needed).
- **Monthly membership granularity** slightly blurs join/leave dates; flagged in the report.
- **Delisted coverage** via DAPI is generally good but not guaranteed for every 2010-era name;
  the report's coverage stats make any gaps visible instead of silent.
