# PA Strategy Backtesting Framework — Design Plan (v0.2 Draft)

> Goal: turn the knowledge in the brain (`wiki/`) into a **reproducible, quantitatively verifiable** backtesting system.
> Related brain pages: `momentum-trend-trading-system`, each setup's Evidence section, `expectancy-and-position-sizing`, `risk-management-vs-setup`.
> Status: **M0–M4 implemented** (see §9 and the README roadmap); next is **M5 — bias defenses**. Locked decisions are in "Decision Log" below.

---

## Decision Log (v0.2 · 2026-06-30)

| # | Topic | Decision |
|---|---|---|
| 1 | Data strategy | **Prototype on free data first (yfinance/Stooq); once the engine works, move to a paid survivorship-free provider (Norgate preferred).** TradingView is a manual validation tool only. |
| 2 | Engine | **Build a lightweight custom event-driven engine** (best fit for the brain's concepts: R-based sizing, gap-through stops, a generic Strategy interface). |
| 3 | First VCP scope | **Daily bars + US equities + VCP; Relative Strength approximated by whole-universe ROC ranking** (a faithful approximation of IBD RS — see brain `relative-strength`). **Industry RS deferred to Phase 2** (needs point-in-time industry data, which free sources can't provide reliably; forcing it would introduce look-ahead bias). |

> Q5 resolved in practice: the framework lives in its own git repo (`backtest_pa`), separate from the brain.

---

## 0. Core Principles

1. **Strict Strategy ⟂ Engine separation.** The engine does NOT know what "VCP" or "Pocket Pivot" is. It only (a) feeds data to the strategy, (b) collects the strategy's *intentions* (signals/orders), (c) simulates execution and bookkeeping, and (d) computes metrics. Swapping strategies must not require changing the engine.
2. **Pluggable data sources.** Neither the engine nor strategies bind directly to any data vendor; a `DataProvider` interface sits in between. Use free data to prototype today, swap to a paid feed tomorrow with no logic changes.
3. **Honesty over pretty numbers.** Guard against the three biases by default — look-ahead, survivorship, and overfitting. The brain itself repeatedly warns about these (`risk-management-vs-setup`, `expectancy-and-position-sizing`).
4. **Metrics aligned with the brain.** Output must include R-multiples, win rate, average win/loss R, **expectancy**, max losing streak, and max drawdown — so results drop straight into the `vcp-breakout` backtest-notes template.
5. **Reproducibility.** Every run is defined by a config file (universe / period / parameters / cost assumptions); the same config produces the same result.

---

## 1. Why Strategy and Backtest Must Be Separate

| Concern | Owner |
|---|---|
| "What counts as a VCP setup? When do we enter? Where's the stop?" | **Strategy** |
| "What price does this order fill at? Slippage / commission? What if a gap jumps the stop?" | **Execution / Broker model** |
| "How much cash do I have? What do I hold? How big should this position be?" | **Portfolio + Risk model** |
| "Over the whole period, what's the win rate / expectancy / drawdown?" | **Metrics / Reporter** |
| "Advance the clock bar-by-bar and coordinate all of the above" | **Engine (generic loop)** |

As long as the `Strategy` interface is stable, VCP / Pocket Pivot / Buyable Gap Up can **all run on the same engine and be compared with the same metrics** (cf. brain `setup-scorecard`).

---

## 2. Layered Architecture

```
                 ┌─────────────────────────────────────┐
   config.yaml → │              Engine (generic)         │
                 │  advance clock bar-by-bar + orchestrate│
                 └──┬───────┬──────────┬─────────┬───────┘
                    │       │          │         │
        ┌───────────▼──┐ ┌──▼──────┐ ┌─▼───────┐ ┌▼──────────┐
        │ DataProvider │ │Strategy │ │Risk /   │ │Execution /│
        │ (iface+adptr)│ │(iface)  │ │Sizing   │ │Broker sim │
        └──────────────┘ └─────────┘ └─────────┘ └───────────┘
                    │                                  │
              ┌─────▼──────┐                    ┌──────▼──────┐
              │MarketContext│ (situation         │ Portfolio   │
              │/Regime      │  awareness: breadth,│ +EquityCurve│
              └─────────────┘  index trend)      └──────┬──────┘
                                                        │
                                                 ┌──────▼──────┐
                                                 │ Metrics /   │
                                                 │ Reporter    │
                                                 └─────────────┘
```

### 2.1 Interface Sketch (pseudo-code; to be reviewed before implementation)

```python
# ---- Data layer: generic, vendor-agnostic ----
class DataProvider(Protocol):
    def trading_calendar(self, start, end) -> list[date]: ...
    def universe(self, on: date) -> list[str]:            # point-in-time members (incl. delisted)
        ...
    def history(self, symbols, start, end,
                fields=("open", "high", "low", "close", "volume")) -> Panel: ...
    def industry(self, symbol, on: date) -> str | None: ...     # sector/industry (optional)
    def earnings_dates(self, symbol) -> list[date]: ...         # earnings (optional; brain says avoid pre-earnings)
    def index(self, name, start, end) -> Series: ...            # benchmark index

# ---- Strategy layer: emits *intentions* only; never touches cash or fills ----
class Strategy(Protocol):
    warmup_bars: int            # history needed before it can compute (MA200, ATR, ...)
    def on_bar(self, ctx: Context) -> list[Signal]: ...
    # Signal = entry/add/exit intention + entry rule + stop rule + (suggested) sizing hint

# ---- Engine: generic, does NOT know VCP ----
class Engine:
    def run(self, strategy, data, broker, risk, calendar) -> BacktestResult: ...
```

`Context` is what the engine hands the strategy at each timestamp: **only data up to and including the current bar** (prevents look-ahead), current positions, cash, and `MarketContext` (market regime). The strategy **cannot see future bars** — the engine enforces this.

### 2.2 Module Responsibilities

- **Engine:** event-driven; iterates each trading day; calls `strategy.on_bar()` to get signals → passes them to `Risk` for sizing → passes to `Broker` to simulate fills → updates `Portfolio` → records.
- **Broker / Execution model:** fill-price model (next open / close / limit), **slippage**, **commission**, **gap-through stop** (a stop jumped by a gap fills at the open — exactly the risk described in brain `gap-risk`).
- **Risk / PositionSizer:** brain formula `size = R$ ÷ stop_distance%` (`expectancy-and-position-sizing`); portfolio-level controls for per-trade risk %, total exposure (heat), and max positions.
- **Portfolio:** cash, positions, daily equity curve, realized/unrealized R.
- **MarketContext / Regime:** computes breadth (T2108), index trend — can act as a gate so strategies "only enter with a market tailwind" (`situation-awareness`). **This is reusable and belongs to no single strategy.**
- **Metrics / Reporter:** see Section 4.

---

## 3. Data Layer — Is TradingView Enough?

**Short answer: TradingView access alone is NOT enough to build this framework, but it's useful as a supporting/validation tool.**

### 3.1 What VCP (and the other setups) actually need
| Data | Used for | Source |
|---|---|---|
| Daily OHLCV (a wide-enough US universe + indices) | trend, breakout, volume | data provider |
| MA 10/20/50/150/200, ATR | stage analysis, stops, volatility contraction | computed from OHLCV |
| **Relative Strength ranking** (cross-sectional) | core stock selection (`relative-strength`) | requires the **whole universe** to compute ROC ranks |
| Sector/industry + industry RS | "industry first" | needs point-in-time industry classification |
| Earnings dates | avoid pre-earnings entries (`gap-risk`) | fundamentals / earnings calendar |
| **Delisted stocks** (survivorship-free) | avoid survivorship bias | needs delisted history |

### 3.2 Why TradingView alone falls short
- **No official bulk historical-data API.** TradingView's data is mainly for charting and for running **Pine Script** (which executes on their platform), not a feed you can pull large amounts of history from into Python.
- **Pine's backtester is weak cross-sectionally.** VCP needs RS ranking and filtering **across thousands of stocks**; Pine is primarily single-symbol, can't do universe-level ranking, and has bar-history limits.
- **Scraping / reverse-engineering = ToS violation + unreliable**, so it's not part of the plan.
- ✅ **TradingView IS useful for:** manually reviewing individual trades, eyeballing charts for confirmation, and quick single-setup sanity checks via Pine. Good as a *second opinion*, not as the *data backbone*.

### 3.3 Recommendation: phased + abstraction layer
**Build the `DataProvider` abstraction first**, so the source can be swapped later:

- **Phase 1 (prototype, free):** `yfinance` or Stooq daily bars; fixed liquid universe (e.g., current S&P 500 / Nasdaq-100).
  - State the limits explicitly in the report: **has survivorship bias, no point-in-time industry/RS, earnings dates need a separate source.** Good enough to "build the engine + validate the workflow."
- **Phase 2 (serious, paid):** survivorship-free + delisted stocks + point-in-time index constituents + industry + earnings dates. Candidates:
  - **Norgate Data** (US equities, purpose-built for this kind of momentum/RS backtesting; includes delisted stocks, index constituents, industry — strong value, popular in the community)
  - **EOD Historical Data (EODHD) / Tiingo / Polygon.io / Nasdaq Data Link** (different trade-offs: price, coverage, earnings/industry)
- **TradingView:** the **manual validation layer** for Phase 1/2, not part of the engine's data backbone.

> In other words: getting TradingView access **helps for sanity checks**, but for credible win-rate/expectancy numbers I recommend a survivorship-free provider in Phase 2 (I lean toward Norgate as the default adapter).

---

## 4. Metrics & Reporting (Aligned with the Brain)

Every run outputs at minimum (all in **R** units — `initial-stop-and-r-multiple`):
- Win rate, average win R, average loss R, **Expectancy = win_rate × avg_win_R − loss_rate × avg_loss_R**
- Max losing streak, max drawdown (in R and %), profit factor
- Equity curve, exposure (% of time in market)
- **Breakdown by regime:** expectancy in bull / bear / range separately (tests the brain's claim that the setups "only work with the trend")
- Benchmark comparison: buy-and-hold the index (`risk-management-vs-setup`)
- **Per-trade trade log:** date / symbol / entry / stop (1R) / exit / result R / regime — pastes directly into the `vcp-breakout` backtest template

Output formats: (a) a markdown/HTML report, (b) optional CSV trade log, (c) optionally **auto-fill** the summary back into the brain setup page's Evidence section (honoring the "compounding artifact" principle).

---

## 5. First Example Strategy: VCP

Mechanize the brain `vcp-breakout` rules (each traceable back to the brain for later auditing):

1. **Universe / stage filter:** price > 150-day MA and 150-day MA rising (Stan Weinstein Stage 2); RS rank ≥ threshold (start by approximating IBD RS with whole-universe ROC ranking).
2. **Contraction detection:** ATR/range narrowing in steps over the last N weeks + volume contraction (`volatility-contraction`).
3. **Build-up / pivot:** a tight, narrow range hugging resistance → define the pivot price (`support-and-resistance`).
4. **Entry:** breakout of the pivot (next open or intraday touch, depending on the fill model).
5. **Stop:** pivot/support − k×ATR (**never placed exactly on support**).
6. **Exit:** trailing = 50-day MA (medium-term) or 20-day MA (short-term) ± ATR (`trailing-stops`); exit on distribution signals (consecutive down days).
7. **Filters:** avoid X days before earnings (`gap-risk`); optional market-regime gate (`situation-awareness`).

Every parameter (N, k, RS threshold, 50- vs 20-day trailing) is **config-adjustable** for sensitivity analysis — but watch out for overfitting (out-of-sample validation, walk-forward).

---

## 6. Bias Defenses (the brain warns; the framework must enforce)

- **Look-ahead:** `Context` exposes only data ≤ current bar; signals computed on close, fills on a later bar. RS ranking and industry must be **point-in-time**.
- **Survivorship:** Phase 2 uses a delisted-inclusive universe; Phase 1 explicitly flags the bias.
- **Overfitting:** split in-sample / out-of-sample; run walk-forward; report parameter sensitivity; treat small samples (<30 trades) conservatively (`expectancy-and-position-sizing`).
- **Realistic costs:** slippage + commission + gap-through stops; no "perfect fills."

---

## 7. Tech Choices

- **Language:** Python (pandas / numpy; reporting via matplotlib/plotly).
- **Build vs. use an existing engine — DECIDED: build lightweight custom engine.**
  - **Custom lightweight event-driven engine (chosen):** most transparent and best-fitting for the brain's concepts (R-based sizing, gap-through stops); controllable and explainable. Cost: we write portfolio/execution ourselves.
  - *zipline-reloaded* (not chosen): US-equity cross-section + Pipeline API is great for RS ranking, but heavier and a steeper learning curve.
  - *backtrader* (not chosen): flexible event-driven, but cross-stock ranking must be built by hand.
  - *vectorbt* (not chosen): vectorized and very fast (great for parameter sweeps), but complex rules / portfolio-level risk management are less natural.

---

## 8. Proposed Directory Layout (`code/`)

```
code/
  BACKTESTING_PLAN.md        # this file
  README.md                  # how to run (to be added)
  pyproject.toml             # dependencies
  config/
    vcp_phase1.yaml          # full definition of one run
  src/btf/                   # backtesting framework
    data/                    # DataProvider interface + adapters (yfinance, norgate, ...)
    engine/                  # generic loop
    broker/                  # execution / slippage / commission / gap
    risk/                    # position sizing, portfolio heat
    portfolio/               # positions, equity curve
    context/                 # MarketContext / regime / breadth
    metrics/                 # R-stats, expectancy, drawdown, report
    strategies/              # ← strategies live OUTSIDE the generic engine
      base.py                #   Strategy interface
      vcp.py                 #   first example
  tests/                     # unit tests (invariants like no look-ahead)
  notebooks/                 # exploration / validation
```

---

## 9. Milestones

- ✅ **M0 — Freeze interfaces:** freeze `DataProvider` / `Strategy` / `Engine` / `Broker` / `BacktestResult` (incl. `Signal` / `Context` fields). No implementation yet.
- ✅ **M1 — Skeleton + fake data:** engine runs a dummy strategy (buy-and-hold) end-to-end; "runs" = books reconcile.
- ✅ **M2 — Phase 1 data:** yfinance/Stooq adapter + fixed universe.
- ✅ **M3 — Metrics:** R-stats / expectancy / drawdown / regime breakdown + report.
- ✅ **M4 — VCP strategy:** mechanize + first report (Phase-1 biases clearly flagged).
- ⏭ **M5 — Bias defenses (next):** walk-forward, out-of-sample, sensitivity — plus the config-YAML run definition (§0 principle 5) as the substrate for parameter sweeps.
- **M6 — Phase 2 data:** swap to a survivorship-free provider, produce the "credible" report, backfill the brain Evidence.
- **M7 — Add more strategies** (Pocket Pivot / Buyable Gap Up) → compare directly via brain `setup-scorecard`.

---

## 10. Open Questions (to settle before building)

1. ~~Data strategy~~ — **DECIDED:** free prototype first, paid survivorship-free later.
2. ~~Custom engine vs. existing lib~~ — **DECIDED:** custom lightweight engine.
3. ~~First VCP scope~~ — **DECIDED:** daily + US equities + VCP; RS via whole-universe ROC; industry RS in Phase 2.
4. **VCP rule simplifications for v1** — confirm: OK to approximate IBD RS with universe ROC ranking and skip industry RS for now? (Tentatively yes, per Decision #3.)
5. ~~Should `code/` become its own git repo~~ — **DECIDED (in practice):** yes; the framework is the standalone `backtest_pa` repo, versioned separately from the brain.

> You said "let's plan slowly," so this is a v0.2 draft. Tell me what to change / sign off, and I'll produce v0.3 and start drafting the M0 interfaces.
