"""VCP strategy tests (M4) — TDD.

Detector units are pure functions over an OHLCV frame; the strategy integration
tests drive ``VcpStrategy.on_bar`` through a ``BacktestContext``; the end-to-end
tests run it through ``BasicEngine`` on synthetic data that forms a real VCP.

Mechanizes wiki/setups/vcp-breakout.md (see module docstring of btf.strategies.vcp).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from btf.context.backtest_context import BacktestContext
from btf.context.market import MarketContext
from btf.core import Direction, Position, Regime, SignalKind
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
# helpers
# --------------------------------------------------------------------------- #
def _frame(closes, highs=None, lows=None, vols=None, start=date(2020, 1, 1)) -> pd.DataFrame:
    n = len(closes)
    highs = highs if highs is not None else [c + 0.5 for c in closes]
    lows = lows if lows is not None else [c - 0.5 for c in closes]
    vols = vols if vols is not None else [1000.0] * n
    idx = pd.DatetimeIndex([pd.Timestamp(start) + timedelta(days=i) for i in range(n)])
    return pd.DataFrame(
        {"open": closes, "high": highs, "low": lows, "close": closes, "volume": vols},
        index=idx,
    )


def _synthetic_vcp() -> pd.DataFrame:
    """A textbook VCP: long Stage-2 uptrend -> two-step contraction -> breakout on the last bar.

    Pivot (prior resistance) sits at 105; the last bar closes at 106 on a volume
    spike. Built so every entry gate passes at the final bar.
    """
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    vols: list[float] = []

    def push(c, h, low, v):
        closes.append(c); highs.append(h); lows.append(low); vols.append(v)

    # Phase 1 — Stage-2 uptrend, 170 bars from 50 -> ~97 (SMA150 rising, price above it).
    for i in range(170):
        c = 50.0 + i * 0.28
        push(c, c + 0.5, c - 0.5, 1000.0)

    # Phase 2a — wider base swing, 10 bars, range ~99..104.5, higher volume.
    for c in [101, 103, 100, 104, 101, 103.5, 100.5, 104, 101, 103.5]:
        push(c, c + 0.5, c - 0.5, 900.0)

    # Phase 2b — tight build-up hugging resistance, 10 bars, range ~103..105, low volume.
    for c in [103.5, 104, 103.8, 104.2, 104, 104.3, 104.1, 104.4, 104.2, 104.5]:
        push(c, c + 0.5, c - 0.5, 700.0)

    # Breakout bar — close clears the 105 pivot on a volume spike.
    push(106.0, 106.5, 104.5, 1600.0)
    return _frame(closes, highs, lows, vols)


# --------------------------------------------------------------------------- #
# pure detector units
# --------------------------------------------------------------------------- #
def test_sma_last_value():
    assert sma(_frame([1, 2, 3, 4, 5])["close"], 5) == pytest.approx(3.0)
    assert sma(_frame([1, 2])["close"], 5) is None  # not enough history


def test_atr_constant_range():
    df = _frame([100, 100, 100, 100, 100])  # high-low = 1.0 every bar
    assert atr(df, 4) == pytest.approx(1.0)


def test_roc_lookback():
    assert roc(_frame([100, 105, 110, 120])["close"], 3) == pytest.approx(0.20)
    assert roc(_frame([100, 105])["close"], 5) is None


def test_in_stage2_true_for_uptrend_false_for_downtrend():
    up = _frame([50 + i * 0.3 for i in range(200)])
    down = _frame([200 - i * 0.3 for i in range(200)])
    assert in_stage2(up, trend_ma=150, slope_lookback=20) is True
    assert in_stage2(down, trend_ma=150, slope_lookback=20) is False


def test_pivot_price_excludes_today():
    # highs: the last (today) bar's 99 must be ignored; pivot = max of prior 5.
    df = _frame([10, 12, 11, 13, 12, 40], highs=[10, 12, 11, 13, 12, 99])
    assert pivot_price(df, base_window=5) == pytest.approx(13.0)


def test_is_tight_true_and_false():
    tight = _frame([100] * 11, highs=[101] * 11, lows=[99] * 11)   # 2% range
    wide = _frame([100] * 11, highs=[120] * 11, lows=[80] * 11)    # 40% range
    assert is_tight(tight, tight_window=10, max_tightness=0.10) is True
    assert is_tight(wide, tight_window=10, max_tightness=0.10) is False


def test_is_contraction_true_when_range_and_volume_shrink():
    df = _synthetic_vcp()
    assert is_contraction(df, tight_window=10, range_ratio=0.7) is True


def test_is_breakout_requires_close_above_pivot_and_volume():
    df = _synthetic_vcp()
    pivot = pivot_price(df, base_window=30)
    assert is_breakout(df, pivot, vol_window=30, vol_expansion=1.3) is True
    # same frame but no volume expansion on the breakout bar -> not a breakout
    weak = df.copy()
    weak.iloc[-1, weak.columns.get_loc("volume")] = 500.0
    assert is_breakout(weak, pivot, vol_window=30, vol_expansion=1.3) is False


def test_initial_stop_below_support():
    df = _synthetic_vcp()
    stop = initial_stop(df, tight_window=10, atr_period=14, k=1.0)
    support = df["low"].iloc[-11:-1].min()
    assert stop < support  # support minus k*ATR


# --------------------------------------------------------------------------- #
# strategy integration via BacktestContext
# --------------------------------------------------------------------------- #
def _ctx(store, as_of, positions=None, universe=None):
    return BacktestContext(
        store=store,
        as_of=as_of,
        cash=100_000.0,
        equity=100_000.0,
        positions=positions or {},
        market=MarketContext(as_of=as_of, regime=Regime.BULL),
        universe=universe or list(store.keys()),
    )


def test_vcp_emits_entry_on_breakout():
    df = _synthetic_vcp()
    store = {"AAA": df}
    as_of = df.index[-1].date()
    signals = VcpStrategy().on_bar(_ctx(store, as_of))
    assert len(signals) == 1
    sig = signals[0]
    assert sig.symbol == "AAA"
    assert sig.kind is SignalKind.ENTRY
    assert sig.trigger_price == pytest.approx(105.0)      # the pivot
    assert sig.stop_price is not None and sig.stop_price < 106.0


def test_vcp_no_entry_when_not_stage2():
    df = _frame([200 - i * 0.3 for i in range(200)])  # downtrend, fails Stage-2
    as_of = df.index[-1].date()
    assert VcpStrategy().on_bar(_ctx({"AAA": df}, as_of)) == []


def test_vcp_no_reentry_while_holding():
    df = _synthetic_vcp()
    as_of = df.index[-1].date()
    pos = {
        "AAA": Position(
            symbol="AAA", direction=Direction.LONG, quantity=10, avg_price=106.0,
            stop_price=101.0, entry_ts=as_of, risk_per_share=5.0,
        )
    }
    # holding above the trail MA -> no new entry, no exit
    signals = VcpStrategy().on_bar(_ctx({"AAA": df}, as_of, positions=pos))
    assert all(s.kind is not SignalKind.ENTRY for s in signals)


def test_vcp_exits_below_trail_ma():
    # Build a held position whose latest close is under its 50-bar SMA -> EXIT.
    closes = [100 + i * 0.3 for i in range(80)] + [90.0]  # last bar dumps below SMA50
    df = _frame(closes)
    as_of = df.index[-1].date()
    pos = {
        "AAA": Position(
            symbol="AAA", direction=Direction.LONG, quantity=10, avg_price=100.0,
            stop_price=80.0, entry_ts=df.index[0].date(), risk_per_share=20.0,
        )
    }
    signals = VcpStrategy(trail_ma=50).on_bar(_ctx({"AAA": df}, as_of, positions=pos))
    exits = [s for s in signals if s.kind is SignalKind.EXIT]
    assert len(exits) == 1 and exits[0].symbol == "AAA"


# --------------------------------------------------------------------------- #
# end-to-end through the engine
# --------------------------------------------------------------------------- #
def _run(provider, symbols, start, end):
    from btf.broker.simple_broker import SimpleBroker
    from btf.engine.basic_engine import BasicEngine
    from btf.risk.fixed_risk_sizer import FixedRiskSizer

    return BasicEngine().run(
        strategy=VcpStrategy(),
        data=provider,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": start, "end": end, "starting_cash": 100_000.0, "symbols": symbols},
    )


def test_vcp_end_to_end_winning_trade_reconciles():
    from btf.data.memory_provider import InMemoryDataProvider

    df = _synthetic_vcp()
    # Append a post-breakout run-up; the engine force-liquidates the open lot at the
    # final (higher) close, booking a winning trade.
    extra_closes = [107 + i for i in range(6)]
    tail = _frame(extra_closes, start=(df.index[-1] + timedelta(days=1)).date())
    full = pd.concat([df, tail])
    provider = InMemoryDataProvider({"AAA": full})

    start, end = full.index[0].date(), full.index[-1].date()
    result = _run(provider, ["AAA"], start, end)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.pnl > 0 and trade.r_multiple > 0
    # books reconcile to the cent
    total_pnl = sum(t.pnl for t in result.trades)
    assert 100_000.0 + total_pnl == pytest.approx(float(result.equity_curve.iloc[-1]), rel=1e-9)


def test_vcp_end_to_end_stops_out_on_breakdown():
    from btf.data.memory_provider import InMemoryDataProvider

    df = _synthetic_vcp()
    # After the breakout entry fills, price collapses through the initial stop.
    crash = _frame([104, 98, 95, 92], start=(df.index[-1] + timedelta(days=1)).date())
    full = pd.concat([df, crash])
    provider = InMemoryDataProvider({"AAA": full})

    start, end = full.index[0].date(), full.index[-1].date()
    result = _run(provider, ["AAA"], start, end)

    assert len(result.trades) == 1
    assert result.trades[0].r_multiple < 0  # stopped out for a loss
