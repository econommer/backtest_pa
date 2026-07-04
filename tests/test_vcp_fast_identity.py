"""M6.5 speed-up identity harness (TDD, written BEFORE the fast implementation).

Two guarantees this file exists to prove, both required by the "bit-identical
output" acceptance bar for the VCP speed-up (see BACKTESTING_PLAN.md / M6.5 plan):

1. **Detector tail-locality** — every pure detector in ``btf.strategies.vcp``
   only reads a bounded tail of the frame it is given. Calling a detector on
   ``df.tail(K)`` for K >= the strategy's computed lookback must return a
   value that is bit-identical (``==``, never ``math.isclose``) to calling it
   on the full frame.

2. **Strategy identity** — an *oracle* re-implementation of ``VcpStrategy.on_bar``
   (a verbatim copy of the pre-speed-up control flow, using only the pure
   detectors and full, unbounded ``ctx.history(sym)`` calls) must produce the
   exact same list of ``Signal``s, bar-for-bar, as the production
   ``VcpStrategy`` after it is changed to fetch bounded history once per
   symbol. This is what actually pins "bit-identical backtest output": if the
   oracle and the sped-up strategy ever disagree, this test fails.

Both tests are harness-first: they pass against the CURRENT (slow) production
strategy too (the oracle just re-derives the same computation), so they are
non-vacuous scaffolding rather than tests that only pass after the rewrite.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

import pandas as pd
import pytest

from btf.context.backtest_context import BacktestContext
from btf.context.market import MarketContext
from btf.core import Direction, Position, Regime, Signal, SignalKind
from btf.strategies.vcp import (
    VcpStrategy,
    atr,
    in_stage2,
    initial_stop,
    is_breakout,
    is_contraction,
    is_tight,
    pivot_price,
    roc,
    sma,
)

# --------------------------------------------------------------------------- #
# lookback formula under test (mirrors what VcpStrategy._lookback must compute)
# --------------------------------------------------------------------------- #
def _expected_lookback(
    trend_ma: int,
    slope_lookback: int,
    rs_lookback: int,
    tight_window: int,
    base_window: int,
    atr_period: int,
    trail_ma: int,
) -> int:
    return max(
        trend_ma + slope_lookback,
        rs_lookback + 1,
        2 * tight_window + 1,
        base_window + 1,
        atr_period + 1,
        trail_ma,
    )


DEFAULT_LOOKBACK = _expected_lookback(
    trend_ma=150, slope_lookback=20, rs_lookback=126,
    tight_window=10, base_window=30, atr_period=14, trail_ma=50,
)


# --------------------------------------------------------------------------- #
# random-walk OHLCV fixture generator
# --------------------------------------------------------------------------- #
def _seeded_ohlcv(seed: int, n: int, start: date = date(2020, 1, 1)) -> pd.DataFrame:
    """A seeded random-walk OHLCV frame, NaN-free, strictly positive closes."""
    rng = random.Random(seed)
    price = 100.0
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    opens: list[float] = []
    vols: list[float] = []
    for _ in range(n):
        drift = rng.uniform(-1.5, 1.6)
        price = max(1.0, price + drift)
        o = max(0.5, price + rng.uniform(-0.5, 0.5))
        c = price
        h = max(o, c) + rng.uniform(0.0, 1.0)
        low = min(o, c) - rng.uniform(0.0, 1.0)
        low = max(0.1, low)
        v = rng.uniform(500.0, 5000.0)
        opens.append(o)
        closes.append(c)
        highs.append(h)
        lows.append(low)
        vols.append(v)
    idx = pd.DatetimeIndex([pd.Timestamp(start) + timedelta(days=i) for i in range(n)])
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


def _shaped_vcp_then_breakdown(n: int, start: date = date(2020, 1, 1)) -> pd.DataFrame:
    """A textbook VCP (stage-2 uptrend -> contraction -> breakout) immediately
    followed by a breakdown through the trail MA, so both an ENTRY and a later
    EXIT are guaranteed to fire deterministically. Same construction as
    ``_synthetic_vcp`` in tests/test_vcp.py, extended with a post-breakout tail
    that first runs up (to clear the pivot debounce) and then rolls over below
    the 50-bar trail SMA so the exit gate is exercised too.
    """
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    vols: list[float] = []

    def push(c: float, h: float, low: float, v: float) -> None:
        closes.append(c)
        highs.append(h)
        lows.append(low)
        vols.append(v)

    # Stage-2 uptrend long enough for SMA150 to be established & rising.
    for i in range(170):
        c = 50.0 + i * 0.28
        push(c, c + 0.5, c - 0.5, 1000.0)
    # Wider base swing (higher volume).
    for c in [101, 103, 100, 104, 101, 103.5, 100.5, 104, 101, 103.5]:
        push(c, c + 0.5, c - 0.5, 900.0)
    # Tight build-up hugging resistance (lower volume).
    for c in [103.5, 104, 103.8, 104.2, 104, 104.3, 104.1, 104.4, 104.2, 104.5]:
        push(c, c + 0.5, c - 0.5, 700.0)
    # Breakout bar.
    push(106.0, 106.5, 104.5, 1600.0)
    # Short run-up to be clearly held above the trail MA for a few bars ...
    for i in range(6):
        c = 107.0 + i
        push(c, c + 0.5, c - 0.5, 1000.0)
    # ... then roll over hard, below the 50-bar trail SMA, to force an exit.
    remaining = n - len(closes)
    for i in range(max(remaining, 0)):
        c = max(1.0, 112.0 - i * 1.2)
        push(c, c + 0.3, c - 0.3, 1000.0)

    idx = pd.DatetimeIndex([pd.Timestamp(start) + timedelta(days=i) for i in range(len(closes))])
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


# --------------------------------------------------------------------------- #
# 1. Detector tail-locality
# --------------------------------------------------------------------------- #
LENGTHS = [5, 8, 14, 15, 20, 21, 29, 30, 31, 49, 50, 51, 100, 149, 150, 169, 170, 171, 300, 600]

# (detector, args) pairs exercised against every seeded frame/length.
_DETECTOR_CASES = [
    ("sma_close", lambda df: sma(df["close"], 150)),
    ("sma_close_trail", lambda df: sma(df["close"], 50)),
    ("atr", lambda df: atr(df, 14)),
    ("roc", lambda df: roc(df["close"], 126)),
    ("in_stage2", lambda df: in_stage2(df, trend_ma=150, slope_lookback=20)),
    ("pivot_price", lambda df: pivot_price(df, base_window=30)),
    ("is_tight", lambda df: is_tight(df, tight_window=10, max_tightness=0.10)),
    ("is_contraction", lambda df: is_contraction(df, tight_window=10, range_ratio=0.7)),
    (
        "is_breakout",
        lambda df: is_breakout(
            df, pivot_price(df, base_window=30), vol_window=30, vol_expansion=1.3
        ),
    ),
    ("initial_stop", lambda df: initial_stop(df, tight_window=10, atr_period=14, k=1.0)),
]


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("length", LENGTHS)
def test_detectors_are_tail_local(seed: int, length: int) -> None:
    df = _seeded_ohlcv(seed=seed, n=length)
    tail = df.tail(DEFAULT_LOOKBACK)
    for name, fn in _DETECTOR_CASES:
        full_result = fn(df)
        tail_result = fn(tail)
        assert full_result == tail_result, (
            f"{name} diverged on seed={seed} length={length}: "
            f"full={full_result!r} tail={tail_result!r}"
        )


def test_tail_locality_harness_catches_an_undersized_lookback() -> None:
    """Sanity check the harness itself: truncating BELOW the safe lookback must
    be caught by at least one (seed, detector) pair on a long-enough history."""
    bad_lookback = DEFAULT_LOOKBACK - 1
    divergence_found = False
    for seed in range(20):
        df = _seeded_ohlcv(seed=seed, n=300)
        tail = df.tail(bad_lookback)
        for _name, fn in _DETECTOR_CASES:
            if fn(df) != fn(tail):
                divergence_found = True
                break
        if divergence_found:
            break
    assert divergence_found, "harness is vacuous: K-1 truncation was not detected"


# --------------------------------------------------------------------------- #
# 2. Strategy identity: oracle (pre-speed-up control flow) vs production
# --------------------------------------------------------------------------- #
def _oracle_rs_percentiles(strategy: VcpStrategy, ctx) -> dict[str, float]:  # type: ignore[no-untyped-def]
    """Verbatim copy of VcpStrategy._rs_percentiles before the speed-up."""
    rocs: dict[str, float] = {}
    for sym in ctx.universe:
        df = ctx.history(sym)
        if len(df) == 0:
            continue
        r = roc(df["close"], strategy.rs_lookback)
        if r is not None:
            rocs[sym] = r
    if not rocs:
        return {}
    values = list(rocs.values())
    n = len(values)
    return {sym: sum(1 for v in values if v <= r) / n for sym, r in rocs.items()}


def _oracle_exit_signal(strategy: VcpStrategy, sym: str, df: pd.DataFrame) -> Signal | None:
    trail = sma(df["close"], strategy.trail_ma)
    if trail is None or float(df["close"].iloc[-1]) >= trail:
        return None
    from btf.core import OrderType

    return Signal(
        symbol=sym,
        kind=SignalKind.EXIT,
        direction=Direction.LONG,
        order_type=OrderType.MARKET,
        reason=f"vcp trail-MA{strategy.trail_ma} exit",
    )


def _oracle_entry_signal(
    strategy: VcpStrategy, sym: str, df: pd.DataFrame, rs: dict[str, float]
) -> Signal | None:
    from btf.core import OrderType

    if not in_stage2(df, strategy.trend_ma, strategy.slope_lookback):
        return None
    if strategy.require_rs:
        pct = rs.get(sym)
        if pct is None or pct < strategy.rs_min_percentile:
            return None
    if not is_contraction(df, strategy.tight_window, strategy.range_ratio):
        return None
    if not is_tight(df, strategy.tight_window, strategy.max_tightness):
        return None
    pivot = pivot_price(df, strategy.base_window)
    if not is_breakout(df, pivot, strategy.base_window, strategy.vol_expansion):
        return None
    stop = initial_stop(df, strategy.tight_window, strategy.atr_period, strategy.stop_atr_mult)
    if stop is None or stop >= float(df["close"].iloc[-1]):
        return None
    return Signal(
        symbol=sym,
        kind=SignalKind.ENTRY,
        direction=Direction.LONG,
        order_type=OrderType.MARKET,
        trigger_price=pivot,
        stop_price=stop,
        reason="vcp breakout",
        meta={"pivot": pivot, "rs_pct": rs.get(sym)},
    )


def _oracle_on_bar(strategy: VcpStrategy, ctx) -> list[Signal]:  # type: ignore[no-untyped-def]
    """Verbatim copy of VcpStrategy.on_bar's control flow before the speed-up."""
    signals: list[Signal] = []
    rs = _oracle_rs_percentiles(strategy, ctx)
    universe = list(ctx.universe)
    held_outside = [s for s in ctx.positions if s not in set(universe)]
    for sym in [*universe, *held_outside]:
        df = ctx.history(sym)
        if len(df) == 0:
            continue
        if sym in ctx.positions:
            exit_sig = _oracle_exit_signal(strategy, sym, df)
            if exit_sig is not None:
                signals.append(exit_sig)
            continue
        entry_sig = _oracle_entry_signal(strategy, sym, df, rs)
        if entry_sig is not None:
            signals.append(entry_sig)
    return signals


# --------------------------------------------------------------------------- #
# multi-symbol synthetic run driving BacktestContext directly, bar by bar
# --------------------------------------------------------------------------- #
SYMBOLS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
N_BARS = 220
# AAA and CCC follow a real VCP-then-breakdown shape so ENTRY and EXIT signals
# are guaranteed; the rest are pure random walks for path/lookback diversity.
SHAPED_SYMBOLS = {"AAA", "CCC"}


def _build_store() -> dict[str, pd.DataFrame]:
    store: dict[str, pd.DataFrame] = {}
    for i, sym in enumerate(SYMBOLS):
        if sym in SHAPED_SYMBOLS:
            store[sym] = _shaped_vcp_then_breakdown(n=N_BARS)
        else:
            store[sym] = _seeded_ohlcv(seed=i, n=N_BARS)
    return store


def _universe_schedule(all_dates: list[pd.Timestamp]) -> dict[pd.Timestamp, list[str]]:
    """Deterministic universe churn: symbols enter/leave over time."""
    schedule: dict[pd.Timestamp, list[str]] = {}
    for i, ts in enumerate(all_dates):
        # FFF only joins the universe partway through (simulates a late index add).
        # CCC leaves the universe partway through (simulates an index removal) but
        # may still be held (see held-outside-universe simulation below).
        members = ["AAA", "BBB", "DDD", "EEE"]
        if i >= 60:
            members.append("FFF")
        if i < 150:
            members.append("CCC")
        schedule[ts] = members
    return schedule


def _position_for(sym: str, avg_price: float, ts: date) -> Position:
    return Position(
        symbol=sym,
        direction=Direction.LONG,
        quantity=10,
        avg_price=avg_price,
        stop_price=avg_price * 0.9,
        entry_ts=ts,
        risk_per_share=avg_price * 0.1,
    )


def _run_both(store: dict[str, pd.DataFrame], *, require_rs: bool) -> tuple[list[list[Signal]], list[list[Signal]]]:
    """Drive oracle + production VcpStrategy across the same bar-by-bar contexts.

    Positions are simulated deterministically (open when the production
    strategy itself signals ENTRY the bar before, close on EXIT) so both
    strategies observe an identical, evolving ``ctx.positions`` at every step
    — the point is to exercise entry/exit control flow and universe churn,
    not to model a realistic broker.
    """
    strategy = VcpStrategy(require_rs=require_rs)
    all_dates = sorted(set.union(*(set(df.index) for df in store.values())))
    schedule = _universe_schedule(all_dates)

    oracle_signals: list[list[Signal]] = []
    prod_signals: list[list[Signal]] = []

    positions: dict[str, Position] = {}
    # Force CCC to be held across its removal from the universe so the
    # held-outside-universe code path is exercised for real.
    forced_hold_symbol = "CCC"
    forced_hold_active = False

    for ts in all_dates:
        as_of = ts.date()
        universe = schedule[ts]

        if forced_hold_symbol not in universe and not forced_hold_active and as_of > all_dates[145].date():
            positions[forced_hold_symbol] = _position_for(
                forced_hold_symbol, float(store[forced_hold_symbol]["close"].loc[:ts].iloc[-1]), as_of
            )
            forced_hold_active = True

        ctx = BacktestContext(
            store=store,
            as_of=as_of,
            cash=100_000.0,
            equity=100_000.0,
            positions=dict(positions),
            market=MarketContext(as_of=as_of, regime=Regime.BULL),
            universe=universe,
        )

        oracle_out = _oracle_on_bar(strategy, ctx)
        prod_out = strategy.on_bar(ctx)
        oracle_signals.append(oracle_out)
        prod_signals.append(prod_out)

        # Apply PRODUCTION signals to the simulated position book so the next
        # bar's ctx.positions reflects real entry/exit activity.
        for sig in prod_out:
            if sig.kind is SignalKind.ENTRY and sig.symbol not in positions:
                price = float(store[sig.symbol]["close"].loc[ts])
                positions[sig.symbol] = _position_for(sig.symbol, price, as_of)
            elif sig.kind is SignalKind.EXIT and sig.symbol in positions:
                del positions[sig.symbol]

    return oracle_signals, prod_signals


def _assert_signals_identical(oracle: list[list[Signal]], prod: list[list[Signal]]) -> None:
    assert len(oracle) == len(prod)
    total_signals = 0
    for i, (o_bar, p_bar) in enumerate(zip(oracle, prod)):
        assert len(o_bar) == len(p_bar), f"bar {i}: signal count differs {len(o_bar)} vs {len(p_bar)}"
        for o_sig, p_sig in zip(o_bar, p_bar):
            assert o_sig == p_sig, f"bar {i}: signal mismatch\n  oracle={o_sig!r}\n  prod={p_sig!r}"
        total_signals += len(o_bar)
    assert total_signals > 0, "harness is vacuous: no signals were produced at all"


def test_strategy_identity_with_rs_enabled() -> None:
    store = _build_store()
    oracle, prod = _run_both(store, require_rs=True)
    _assert_signals_identical(oracle, prod)


def test_strategy_identity_with_rs_disabled() -> None:
    store = _build_store()
    oracle, prod = _run_both(store, require_rs=False)
    _assert_signals_identical(oracle, prod)
