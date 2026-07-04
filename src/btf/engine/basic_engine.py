"""``BasicEngine`` — the concrete event-driven daily loop (implements Engine).

Advances the clock bar-by-bar and stays strategy-agnostic: it feeds a ``Context``,
collects ``Signal``s, sizes, simulates fills, bookkeeps via ``Portfolio``, and
computes ``BacktestResult``. It knows nothing about "buy-and-hold" or "VCP".

Anti-look-ahead: a strategy decides on bar *t*'s close; its orders fill at bar
*t+1*'s open (carried in ``pending_orders``). See M1 design spec §4.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence, cast

import numpy as np
import pandas as pd

from btf.context.backtest_context import BacktestContext
from btf.context.market import MarketContext
from btf.core import Bar, FillKind, Order, Regime
from btf.broker.broker import Broker
from btf.data.provider import DataProvider
from btf.metrics.compute import compute_metrics, compute_regime_breakdown
from btf.metrics.result import BacktestResult
from btf.portfolio.portfolio import Portfolio
from btf.regime.classifier import RegimeClassifier, SmaRegimeClassifier
from btf.risk.sizer import PositionSizer
from btf.strategies.base import Strategy


@dataclass(frozen=True, slots=True)
class _Cursor:
    """Precomputed positional view of one symbol's frame (M6.5 speed-up).

    ``_bars_on`` used to do a per-symbol, per-bar ``ts not in df.index`` +
    ``df.loc[ts]`` — a pandas label lookup against the FULL frame on every one
    of ``len(calendar) * len(symbols)`` calls. Built once per run instead: a
    plain dict from Timestamp -> integer position (O(1) membership + lookup)
    plus the OHLCV columns as numpy arrays (no per-access pandas overhead).
    Bit-identical values to ``float(df.loc[ts, col])`` for the same (sym, ts).
    """

    index_pos: dict[pd.Timestamp, int]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


class BasicEngine:
    """Runs one backtest over a strategy, data, broker, and sizer."""

    def __init__(self, classifier: RegimeClassifier | None = None) -> None:
        # Pluggable regime engine; run()'s frozen signature stays untouched (M3 E2).
        self._classifier: RegimeClassifier = classifier or SmaRegimeClassifier()

    def run(
        self,
        strategy: Strategy,
        data: DataProvider,
        broker: Broker,
        sizer: PositionSizer,
        config: Mapping[str, object],
    ) -> BacktestResult:
        start: date = config["start"]  # type: ignore[assignment]
        end: date = config["end"]  # type: ignore[assignment]
        starting_cash = float(config["starting_cash"])  # type: ignore[arg-type]
        cfg_symbols = config.get("symbols")
        symbols = (
            list(cast(Sequence[str], cfg_symbols)) if cfg_symbols else list(data.universe(start))
        )

        store = self._build_store(data, symbols, start, end)
        cursors = self._build_cursors(store)
        calendar = data.trading_calendar(start, end)
        portfolio = Portfolio(starting_cash)
        pending_orders: list[Order] = []

        benchmark_name = config.get("benchmark")
        benchmark = data.index(cast(str, benchmark_name), start, end) if benchmark_name else None
        day_regimes: dict[date, Regime] = {}

        last_t = calendar[-1] if calendar else None
        for idx, t in enumerate(calendar):
            bars_t = self._bars_on(cursors, symbols, t)

            # 0. Classify the market regime from benchmark history <= t (same firewall as
            #    prices). Done first so entries filled today are tagged look-ahead-free.
            regime_t, index_trend_t = self._classify(benchmark, t)
            day_regimes[t] = regime_t

            # 2. Execute orders decided yesterday, at today's open.
            order_by_symbol = {o.symbol: o for o in pending_orders}
            for fill in broker.execute(pending_orders, bars_t):
                if fill.kind in (FillKind.ENTRY, FillKind.ADD):
                    portfolio.apply_entry(fill, order_by_symbol[fill.symbol], regime_t)
                else:
                    portfolio.apply_exit(fill)

            # 3. Sweep resting stops against today's bar (after fills → no double-close).
            for fill in broker.sweep_stops(portfolio.snapshot_positions(), bars_t):
                portfolio.apply_exit(fill)

            # 3b. Delisting cash-out: a held symbol with no bar today AND no bars
            # remaining in the store ever again has left the exchange (acquisition,
            # bankruptcy, index removal with the data feed dropped). Real-world
            # holders are cashed out at the final print — synthesize that exit here
            # via the same apply_exit mechanism _force_liquidate uses, rather than
            # leaving the lot locked until end-of-run (survivorship-free PIT data,
            # M6 fix). A held symbol with a bar today is unaffected.
            for sym in portfolio.open_symbols():
                if sym in bars_t:
                    continue
                if self._has_future_bars(store, sym, t):
                    continue  # temporary gap, not a delisting
                self._delist_exit(portfolio, store, sym, t)

            # 4. Mark-to-market at today's close and record equity. A held symbol
            # missing today's bar (temporary gap, or delisted just above) still needs
            # a value — fall back to its last available close <= t so equity never
            # phantom-drops to cash-only for one day (M6 fix).
            closes = {sym: bar.close for sym, bar in bars_t.items()}
            for sym in portfolio.open_symbols():
                if sym not in closes:
                    fallback = self._last_close_on_or_before(store, sym, t)
                    if fallback is not None:
                        closes[sym] = fallback
            equity = portfolio.mark(closes)
            portfolio.record_equity(t, equity)

            # 5. Build the as-of context (the firewall slices the store to <= t).
            ctx = BacktestContext(
                store=store,
                as_of=t,
                cash=portfolio.cash,
                equity=equity,
                positions=portfolio.snapshot_positions(),
                market=MarketContext(as_of=t, regime=regime_t, index_trend=index_trend_t),
                universe=data.universe(t),
            )

            # 6-7. Ask the strategy, size the signals.
            signals = strategy.on_bar(ctx) if idx >= strategy.warmup_bars else []
            orders = sizer.size(signals, ctx)

            # 8. Carry to tomorrow's open — orders decided on the final bar have no t+1
            #    to fill against, so they are intentionally dropped.
            pending_orders = [] if t == last_t else orders

        # After the loop: force-liquidate any open lots at the final bar's close (D1).
        if last_t is not None:
            self._force_liquidate(portfolio, store, last_t)

        equity_curve = self._equity_series(portfolio)
        metrics = compute_metrics(portfolio.trades, equity_curve)
        # M3: populate the two fields M1 stubbed — only when a benchmark was configured.
        benchmark_curve = (
            self._benchmark_curve(benchmark, equity_curve, starting_cash)
            if benchmark_name
            else None
        )
        regime_breakdown = (
            compute_regime_breakdown(portfolio.trades, equity_curve, day_regimes)
            if benchmark_name
            else {}
        )
        return BacktestResult(
            config=config,
            equity_curve=equity_curve,
            metrics=metrics,
            trades=portfolio.trades,
            benchmark_curve=benchmark_curve,
            regime_breakdown=regime_breakdown,
        )

    # ---- helpers -------------------------------------------------------------

    def _classify(self, benchmark: pd.Series | None, t: date) -> tuple[Regime, float | None]:
        if benchmark is None:
            return Regime.UNKNOWN, None
        history = benchmark.loc[: pd.Timestamp(t)]  # index sorted → strictly <= t
        return self._classifier.classify(history)

    @staticmethod
    def _benchmark_curve(
        benchmark: pd.Series | None, equity_curve: pd.Series, starting_cash: float
    ) -> pd.Series | None:
        """Buy-and-hold-the-index equity, normalised to ``starting_cash`` (M3 E4)."""
        if benchmark is None or len(benchmark) == 0 or len(equity_curve) == 0:
            return None
        bench = benchmark.copy()
        bench.index = pd.DatetimeIndex(bench.index)
        aligned = bench.reindex(equity_curve.index, method="ffill").bfill()
        first = aligned.first_valid_index()
        if first is None:
            return None
        base = float(aligned.loc[first])
        if base == 0:
            return None
        return (starting_cash * aligned / base).rename("benchmark")

    @staticmethod
    def _build_store(
        data: DataProvider, symbols: list[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        hist = data.history(symbols, start, end)
        store: dict[str, pd.DataFrame] = {}
        if len(hist) == 0:
            return store
        for sym, group in hist.groupby(level="symbol"):
            frame = group.droplevel("symbol").sort_index()
            store[sym] = frame
        return store

    @staticmethod
    def _build_cursors(store: Mapping[str, pd.DataFrame]) -> dict[str, _Cursor]:
        """Precompute a ``_Cursor`` per symbol once per run (M6.5 speed-up)."""
        cursors: dict[str, _Cursor] = {}
        for sym, df in store.items():
            cursors[sym] = _Cursor(
                index_pos={ts: i for i, ts in enumerate(df.index)},
                open=df["open"].to_numpy(dtype=float),
                high=df["high"].to_numpy(dtype=float),
                low=df["low"].to_numpy(dtype=float),
                close=df["close"].to_numpy(dtype=float),
                volume=df["volume"].to_numpy(dtype=float),
            )
        return cursors

    @staticmethod
    def _bars_on(cursors: Mapping[str, _Cursor], symbols: list[str], t: date) -> dict[str, Bar]:
        ts = pd.Timestamp(t)
        bars: dict[str, Bar] = {}
        for sym in symbols:
            cur = cursors.get(sym)
            if cur is None:
                continue
            i = cur.index_pos.get(ts)
            if i is None:
                continue
            bars[sym] = Bar(
                symbol=sym,
                ts=t,
                open=float(cur.open[i]),
                high=float(cur.high[i]),
                low=float(cur.low[i]),
                close=float(cur.close[i]),
                volume=float(cur.volume[i]),
            )
        return bars

    @staticmethod
    def _has_future_bars(store: Mapping[str, pd.DataFrame], sym: str, t: date) -> bool:
        """Whether ``sym`` has any bar strictly after ``t`` in the store (still trading)."""
        df = store.get(sym)
        if df is None:
            return False
        return bool((df.index > pd.Timestamp(t)).any())

    @staticmethod
    def _last_close_on_or_before(
        store: Mapping[str, pd.DataFrame], sym: str, t: date
    ) -> float | None:
        df = store.get(sym)
        if df is None:
            return None
        hist = df.loc[: pd.Timestamp(t)]
        if hist.empty:
            return None
        return float(hist["close"].iloc[-1])

    @staticmethod
    def _delist_exit(
        portfolio: Portfolio, store: Mapping[str, pd.DataFrame], sym: str, t: date
    ) -> None:
        """Synthesize an exit at ``sym``'s last available close (delisting cash-out)."""
        from btf.core import Direction, Fill

        df = store.get(sym)
        if df is None:
            return
        hist = df.loc[: pd.Timestamp(t)]
        if hist.empty:
            return
        last_ts = hist.index[-1].date()
        close = float(hist["close"].iloc[-1])
        pos = portfolio.snapshot_positions()[sym]
        portfolio.apply_exit(
            Fill(
                symbol=sym,
                ts=last_ts,
                price=close,
                quantity=pos.quantity,
                direction=Direction.LONG,
                kind=FillKind.EXIT,
                reason="delisted",
            )
        )

    @staticmethod
    def _force_liquidate(portfolio: Portfolio, store: Mapping[str, pd.DataFrame], t: date) -> None:
        from btf.core import Direction, Fill

        ts = pd.Timestamp(t)
        for sym in portfolio.open_symbols():
            df = store.get(sym)
            if df is None:
                continue
            row = df.loc[ts] if ts in df.index else df.loc[:ts].iloc[-1]
            close = float(row["close"])
            pos = portfolio.snapshot_positions()[sym]
            portfolio.apply_exit(
                Fill(
                    symbol=sym,
                    ts=t,
                    price=close,
                    quantity=pos.quantity,
                    direction=Direction.LONG,
                    kind=FillKind.EXIT,
                    reason="final liquidation",
                )
            )
        # Final equity reflects the post-liquidation flat book (all cash).
        if portfolio.equity_curve:
            portfolio.equity_curve[-1] = (portfolio.equity_curve[-1][0], portfolio.cash)

    @staticmethod
    def _equity_series(portfolio: Portfolio) -> pd.Series:
        if not portfolio.equity_curve:
            return pd.Series(dtype=float)
        dates = [d for d, _ in portfolio.equity_curve]
        values = [v for _, v in portfolio.equity_curve]
        return pd.Series(values, index=pd.DatetimeIndex(dates), name="equity")
