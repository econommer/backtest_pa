# PA Strategy Backtesting Framework (`btf`)

A reproducible, quantitatively verifiable backtesting engine for price-action
strategies. See **`BACKTESTING_PLAN.md`** for the authoritative design and
**`CLAUDE.md`** for conventions. Strategy ⟂ Engine: the engine knows nothing
about any specific strategy; data flows in through the vendor-agnostic
`DataProvider` interface.

## Install

```bash
pip install -e '.[dev]'    # tests + data adapters (yfinance, pyarrow)
# or, runtime data adapters only:
pip install -e '.[data]'
```

## Tests

```bash
python -m pytest
```

The unit/contract/cash-guard tests are fully offline and deterministic. The
real-data **smoke test** (`tests/test_smoke_real_data.py`) *skips* until a data
snapshot is cached (see below).

## Market data (Phase 1, free)

Two adapters implement `DataProvider`, both producing output byte-for-byte
identical to `InMemoryDataProvider` (`history()` → MultiIndex `["symbol","ts"]`,
lowercase float OHLCV, tz-naive midnight index, sorted, de-duped, NaN-dropped):

- **`YFinanceDataProvider`** — primary; split/dividend-adjusted daily bars.
- **`StooqDataProvider`** — fallback; Stooq CSV, adjusted daily bars.

Both **fetch → normalize → cache to parquet**, keyed by `source+symbol+range`.
A cache hit skips the network, so **a run pins its data snapshot** to whatever
parquet files sit under the cache directory — reruns are fast and deterministic.

```python
from datetime import date
from btf.data import YFinanceDataProvider

provider = YFinanceDataProvider(
    ["AAPL", "MSFT"], date(2018, 1, 1), date(2023, 1, 1),
    cache_dir="data_cache", benchmark_symbol="SPY",
)
provider.history(["AAPL", "MSFT"], date(2018, 1, 1), date(2023, 1, 1))
```

### Pinning the snapshot for the smoke test

The smoke test runs `BuyAndHold` over a fixed real universe defined in
`btf.data.phase1_snapshot`. Populate the cache once, in a network-enabled
environment:

```bash
python scripts/fetch_snapshot.py     # writes ./data_cache/yfinance/*.parquet
```

Afterwards the smoke test runs fully offline. To pin a snapshot across machines,
keep `data_cache/` around or point runs at a shared copy with `BTF_CACHE_DIR`.
(`data_cache/` is git-ignored by default to avoid committing large binaries.)

> ⚠ **Survivorship bias (Phase 1).** The free adapters serve only
> currently-listed symbols, so any static universe excludes delisted names and is
> upward-biased. Reports must flag this (`phase1_snapshot.survivorship_warning()`);
> Phase 2 swaps in a delisted-inclusive provider.
