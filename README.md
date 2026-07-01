# `btf` — PA Strategy Backtesting Framework

A **reproducible, quantitatively verifiable** backtesting engine for price-action
strategies. It turns the trading knowledge in the sibling
[`../wiki/`](../wiki/) "brain" into numbers you can defend: win rate, expectancy
in **R units**, drawdown, and a benchmark you have to beat.

> **Study tool, not a trading system.** This framework *documents and measures*
> price-action methods. It never places live trades, moves money, or gives
> buy/sell advice. See [`CLAUDE.md`](CLAUDE.md) and [`BACKTESTING_PLAN.md`](BACKTESTING_PLAN.md).

```
Python 3.11+  ·  type-hinted, Protocol-based interfaces  ·  83 tests green  ·  BuyAndHold + VCP  ·  no zipline/backtrader — custom event-driven engine
```

---

## The one principle: **Strategy ⟂ Engine**

The engine knows *nothing* about "VCP" or "buy-and-hold". It feeds a strategy an
as-of-today view of the market, collects the strategy's *intentions* (`Signal`s),
then simulates execution, bookkeeping, and metrics. Swap the strategy or the data
vendor without touching the other side.

```
  DataProvider ─┐                          each bar t, inside BasicEngine:
 (yfinance /    │
  Stooq /       ├─▶  Context          the strategy's as-of view — data ≤ today only
  parquet)      │      │
                │      ▼
                │   Strategy.on_bar() ──▶ [Signals]     "I intend to enter/exit" (no prices, no sizing)
                │                            │
                │                            ▼
                │   PositionSizer         turns signals into orders, risk sized in R
                │                            │
                │                            ▼
                │   Broker                fills at t+1 open · slippage · commission · gap-through stops
                │                            │
                │                            ▼
                └─  Portfolio            cash · positions · trades · equity curve
                                             │
                                             ▼
                                     BacktestResult ─▶ Metrics: R-stats, expectancy, drawdown,
                                                       regime breakdown, benchmark overlay
```

**Anti-look-ahead is structural, not a convention:** the strategy decides on bar
*t*'s close; orders fill at bar *t+1*'s open. `Context` can only see data ≤ today,
enforced by [`tests/test_no_lookahead.py`](tests/test_no_lookahead.py).

Source layout ([plan §8](BACKTESTING_PLAN.md)):

```
src/btf/
  data/        DataProvider + yfinance/Stooq adapters, parquet cache, normalisation
  context/     the as-of-today firewall the strategy sees
  strategies/  BuyAndHold + VCP breakout; Pocket-Pivot/BGU plug in on the same interface
  risk/        position sizing (fixed-risk / R-based)
  broker/      fills, slippage, commission, gap-through stops
  portfolio/   cash, positions, trades, equity curve
  regime/      SMA-based market-regime classifier (for regime breakdown)
  metrics/     R-stats, expectancy, drawdown, benchmark → BacktestResult
  engine/      the event-driven daily loop that wires it all together
```

---

## Quickstart

```bash
pip install -e '.[data]'      # runtime + data adapters (yfinance, pyarrow)
# or  pip install -e '.[dev]' # + pytest / mypy / ruff
python -m pytest              # 83 unit/contract/no-look-ahead tests, fully offline
```

### See it run on real data — Index vs Equities vs Commodity

[`scripts/run_asset_classes.py`](scripts/run_asset_classes.py) drives the full
pipeline (fetch → cache → engine → metrics) on live Yahoo Finance data across three
asset classes, then reconciles the books:

```bash
python scripts/run_asset_classes.py
```

Buy-and-hold, equal-weight, **2015-01-02 → 2024-12-31** (10y), $100k, SPY benchmark:

| Asset class | Universe                          | Total return | CAGR  | Max DD | Books |
|-------------|-----------------------------------|-------------:|------:|-------:|:-----:|
| **Index**   | SPY, QQQ, DIA, IWM                |       +246%  | 13.2% |   34%  |  ✅   |
| **Equities**| AAPL, MSFT, NVDA, JPM, XOM, JNJ   |     +5,023%  | 48.3% |   55%  |  ✅   |
| **Commodity** | GLD, SLV, USO, DBC, UNG         |        +15%  |  1.4% |   41%  |  ✅   |
| _benchmark_ | SPY buy&hold                      |       +240%  | 13.0% |   34%  |   —   |

*Reading it:* the equity basket is dominated by the NVDA outlier (a textbook
selection-bias trap); commodities took index-sized drawdowns for almost no return;
broad indices roughly tracked SPY, as they should. `Books ✅` means final equity =
starting cash + Σ trade P&L to the cent — the engine's accounting closes.

> ⚠ **Phase-1 numbers are upward-biased.** These are hand-picked, *currently-listed*
> symbols — no delisted names, and the winners were visible in advance. This is a
> pipeline demo, not an edge. Survivorship-free data lands in Phase 2 (M6).

### The first real strategy — VCP breakout

[`scripts/run_vcp.py`](scripts/run_vcp.py) runs the mechanized **VCP** setup
([Minervini's Volatility Contraction Pattern](../wiki/setups/vcp-breakout.md)) through
the engine and reports the brain's backtest-notes metrics in **R units** — Stage-2
trend filter → whole-universe RS ranking → contraction → pivot breakout → `support − ATR`
stop → 50-day-MA trailing exit:

```bash
python scripts/run_vcp.py
```

**2015 → 2025, 1% risk/trade, SPY regime, next-open fills w/ slippage + commission:**

| Asset class | Syms | Trades | Win% | Avg win | Avg loss | **Expectancy** | Profit factor | Max DD |
|-------------|-----:|-------:|-----:|--------:|---------:|---------------:|--------------:|-------:|
| **Equities**  | 30 | 73 | 38% | 1.98R | 0.55R | **+0.42R** | 1.96 | 10% |
| **Commodity** | 10 | 17 | 53% | 1.33R | 0.73R | **+0.36R** | 2.12 |  5% |
| **Index**     | 12 | 20 | 45% | 1.26R | 0.63R | **+0.22R** | 1.50 |  6% |

*Reading it:* textbook trend-following shape — a **low win rate paid for by wins ~3–4×
the size of losses**, so expectancy stays positive (matches Minervini's own ~50–60%
and "cut losses fast, let winners run"). Equities give the setup the most to work with
(73 trades, best expectancy); on the ETF baskets clean setups are rarer — as expected
for an equity momentum pattern. Books reconcile to the cent across all three.

> ⚠ **Not an edge yet.** Same Phase-1 survivorship/selection bias as above, and the
> Index/Commodity samples are **< 30 trades — not statistically significant**. A
> credible number needs walk-forward + out-of-sample (M5) on survivorship-free data
> (M6). This is the *first* VCP report, honestly flagged — not a validated strategy.

### Backtest a strategy in code

```python
from datetime import date
from btf.data.yfinance_provider import YFinanceDataProvider
from btf.engine.basic_engine import BasicEngine
from btf.broker.simple_broker import SimpleBroker
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold

provider = YFinanceDataProvider(
    ["AAPL", "MSFT"], date(2018, 1, 1), date(2023, 1, 1),
    cache_dir="data_cache", benchmark_symbol="SPY",
)
result = BasicEngine().run(
    strategy=BuyAndHold(),
    data=provider,
    broker=SimpleBroker(commission_per_share=0.005, slippage_pct=0.0005),
    sizer=FixedRiskSizer(risk_pct=0.02),
    config={"start": date(2018, 1, 1), "end": date(2023, 1, 1),
            "starting_cash": 100_000.0, "symbols": ["AAPL", "MSFT"], "benchmark": "SPY"},
)
print(result.metrics)                    # expectancy, win rate, drawdown — all in R
print(result.equity_curve.iloc[-1])      # final equity
```

Swap `BuyAndHold` for `VcpStrategy()` (from `btf.strategies.vcp`) — same engine, same
config, no other change — to run the VCP report above.

---

## Market data (Phase 1, free)

Two adapters implement `DataProvider`, both emitting output byte-for-byte identical
to the in-memory provider (`history()` → MultiIndex `["symbol","ts"]`, lowercase
float OHLCV, tz-naive midnight index, sorted, de-duped, NaN-dropped):

- **`YFinanceDataProvider`** — primary; split/dividend-adjusted daily bars.
- **`StooqDataProvider`** — fallback; adjusted daily bars from Stooq CSV.

Both **fetch → normalise → cache to parquet**, keyed by `source+symbol+range`. A
cache hit skips the network, so **a run pins its data snapshot** to whatever parquet
sits under the cache dir — reruns are fast, offline, and deterministic. Point runs
at a shared snapshot with `BTF_CACHE_DIR`. (`data_cache/` is git-ignored to avoid
committing binaries.)

The offline **smoke test** ([`tests/test_smoke_real_data.py`](tests/test_smoke_real_data.py))
runs `BuyAndHold` over a pinned universe ([`phase1_snapshot.py`](src/btf/data/phase1_snapshot.py))
and *skips* until you populate the cache once:

```bash
python scripts/fetch_snapshot.py     # writes ./data_cache/yfinance/*.parquet, then offline forever
```

---

## Roadmap

| | Milestone | Status |
|---|---|---|
| **M0** | Freeze interfaces (`DataProvider` / `Strategy` / `Engine` / `Broker` / `Signal` / `Context`) | ✅ done |
| **M1** | Skeleton + fake data — engine runs buy-and-hold end-to-end, books reconcile | ✅ done |
| **M2** | Phase-1 data — yfinance/Stooq adapters, parquet cache, pinned universe | ✅ done |
| **M3** | Metrics — R-stats / expectancy / drawdown / regime breakdown + benchmark | ✅ done |
| **M4** | VCP strategy — mechanized rules + first report (biases flagged) | ✅ done |
| **M5** | **Bias defenses** — walk-forward, out-of-sample, parameter sensitivity | ⏭ **next** |
| **M6** | Phase-2 data — survivorship-free provider, the "credible" report | ⬜ |
| **M7** | More strategies — Pocket Pivot, Buyable Gap Up — compared on one engine | ⬜ |

---

## Bias defenses (the brain insists on these)

- **Look-ahead** — `Context` exposes only data ≤ today; signals on close, fills at
  the next open; regime/RS are point-in-time. Guarded by tests.
- **Survivorship** — Phase 1 flags the bias loudly in every report; Phase 2 swaps in
  a delisted-inclusive universe.
- **Overfitting** — in-sample/out-of-sample split, walk-forward, and
  parameter-sensitivity reporting (M5); <30-trade samples treated conservatively.
- **Realistic costs** — slippage + commission + **gap-through stops** (a gap can jump
  a stop → fill at the open, not the stop price).

## Why the rules are the rules

Every mechanized rule traces back to a page in the brain:
[`relative-strength`](../wiki/concepts/relative-strength.md),
[`initial-stop-and-r-multiple`](../wiki/concepts/initial-stop-and-r-multiple.md),
[`expectancy-and-position-sizing`](../wiki/concepts/expectancy-and-position-sizing.md),
[`volatility-contraction`](../wiki/concepts/volatility-contraction.md),
[`gap-risk`](../wiki/concepts/gap-risk.md); setup
[`vcp-breakout`](../wiki/setups/vcp-breakout.md); playbook
[`momentum-trend-trading-system`](../wiki/playbooks/momentum-trend-trading-system.md).

---

*Not financial advice. For studying and backtesting price-action strategies only.*
