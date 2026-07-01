"""Component unit tests for M1 (design spec §8.4)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from btf.broker.simple_broker import SimpleBroker
from btf.context.backtest_context import BacktestContext
from btf.context.market import MarketContext
from btf.core import (
    Bar,
    Direction,
    Fill,
    FillKind,
    Order,
    OrderType,
    Position,
    Regime,
    Signal,
    SignalKind,
    Trade,
)
from btf.metrics.compute import compute_metrics
from btf.portfolio.portfolio import Portfolio
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from tests.m1_fixtures import uptrend_provider


# --- InMemoryDataProvider ----------------------------------------------------

def test_provider_calendar_and_history_bounds():
    prov = uptrend_provider(days=10)
    cal = prov.trading_calendar(date(2020, 1, 3), date(2020, 1, 6))
    assert cal == [date(2020, 1, 3), date(2020, 1, 4), date(2020, 1, 5), date(2020, 1, 6)]
    hist = prov.history(["AAA"], date(2020, 1, 3), date(2020, 1, 6))
    assert list(hist.index.get_level_values("ts").date) == cal
    assert set(hist.columns) == {"open", "high", "low", "close", "volume"}


def test_provider_index_raises_without_benchmark():
    with pytest.raises(KeyError):
        uptrend_provider().index("SPX", date(2020, 1, 1), date(2020, 1, 5))


# --- BacktestContext (firewall) ----------------------------------------------

def _ctx_from(prov, as_of, cash=10_000.0, equity=10_000.0):
    hist = prov.history(["AAA"], date(2020, 1, 1), date(2020, 1, 31))
    store = {"AAA": hist.droplevel("symbol")}
    return BacktestContext(
        store=store,
        as_of=as_of,
        cash=cash,
        equity=equity,
        positions={},
        market=MarketContext(as_of=as_of, regime=Regime.UNKNOWN),
        universe=["AAA"],
    )


def test_context_never_reveals_future():
    ctx = _ctx_from(uptrend_provider(days=10), as_of=date(2020, 1, 5))
    hist = ctx.history("AAA")
    assert max(hist.index).date() == date(2020, 1, 5)
    assert ctx.bar("AAA").ts == date(2020, 1, 5)


def test_context_lookback_and_missing_bar():
    ctx = _ctx_from(uptrend_provider(days=10), as_of=date(2020, 1, 5))
    assert len(ctx.history("AAA", lookback=2)) == 2
    assert ctx.bar("ZZZ") is None


# --- SimpleBroker ------------------------------------------------------------

def _bar(sym="AAA", o=100.0, h=105.0, low=95.0, c=102.0):
    return Bar(symbol=sym, ts=date(2020, 1, 2), open=o, high=h, low=low, close=c, volume=1000.0)


def test_broker_fills_at_open_with_slippage_sign():
    broker = SimpleBroker(slippage_pct=0.01, commission_per_share=0.02)
    order = Order("AAA", Direction.LONG, SignalKind.ENTRY, OrderType.MARKET, 10, None, 90.0, 12.0)
    (fill,) = broker.execute([order], {"AAA": _bar(o=100.0)})
    assert fill.price == pytest.approx(101.0)  # buy pays up
    assert fill.kind is FillKind.ENTRY
    assert fill.commission == pytest.approx(0.2)


def test_broker_rejects_non_market_order():
    broker = SimpleBroker()
    order = Order("AAA", Direction.LONG, SignalKind.ENTRY, OrderType.STOP, 10, 110.0, 90.0, 20.0)
    with pytest.raises(NotImplementedError):
        broker.execute([order], {"AAA": _bar()})


def test_broker_gap_through_stop_fills_at_open():
    broker = SimpleBroker()
    pos = Position("AAA", Direction.LONG, 10, 100.0, 95.0, date(2020, 1, 1), 5.0)
    # bar opens at 90 (below the 95 stop) → gap-through fills at the open.
    (fill,) = broker.sweep_stops({"AAA": pos}, {"AAA": _bar(o=90.0, low=88.0)})
    assert fill.kind is FillKind.STOP_OUT
    assert fill.price == pytest.approx(90.0)


def test_broker_stop_fills_at_stop_when_no_gap():
    broker = SimpleBroker()
    pos = Position("AAA", Direction.LONG, 10, 100.0, 95.0, date(2020, 1, 1), 5.0)
    # opens at 98, dips to 94 (< stop) intrabar → fills at the stop price, not the open.
    (fill,) = broker.sweep_stops({"AAA": pos}, {"AAA": _bar(o=98.0, low=94.0)})
    assert fill.price == pytest.approx(95.0)


# --- FixedRiskSizer ----------------------------------------------------------

def test_sizer_quantity_math_and_cash_cap():
    ctx = _ctx_from(uptrend_provider(days=10), as_of=date(2020, 1, 5), cash=1_000.0, equity=10_000.0)
    close = ctx.bar("AAA").close  # 104.5
    # risk_pct=0.01, equity=10000 → risk$=100; stop 4.5 below → qty=floor(100/4.5)=22,
    # but cash cap floor(1000/104.5)=9 wins.
    sizer = FixedRiskSizer(risk_pct=0.01)
    sig = Signal("AAA", SignalKind.ENTRY, stop_price=close - 4.5, order_type=OrderType.MARKET)
    (order,) = sizer.size([sig], ctx)
    assert order.quantity == 9
    assert order.risk_per_share == pytest.approx(4.5)


def test_sizer_drops_non_positive_risk():
    ctx = _ctx_from(uptrend_provider(days=10), as_of=date(2020, 1, 5))
    sizer = FixedRiskSizer(risk_pct=0.01)
    close = ctx.bar("AAA").close
    sig = Signal("AAA", SignalKind.ENTRY, stop_price=close + 1.0, order_type=OrderType.MARKET)
    assert sizer.size([sig], ctx) == []


def test_sizer_exit_uses_full_position_qty():
    prov = uptrend_provider(days=10)
    store = {"AAA": prov.history(["AAA"], date(2020, 1, 1), date(2020, 1, 31)).droplevel("symbol")}
    pos = Position("AAA", Direction.LONG, 7, 100.0, 90.0, date(2020, 1, 1), 10.0)
    ctx = BacktestContext(store, date(2020, 1, 5), 1_000.0, 5_000.0, {"AAA": pos},
                          MarketContext(date(2020, 1, 5), Regime.UNKNOWN), ["AAA"])
    sizer = FixedRiskSizer(risk_pct=0.01)
    (order,) = sizer.size([Signal("AAA", SignalKind.EXIT, order_type=OrderType.MARKET)], ctx)
    assert order.kind is SignalKind.EXIT and order.quantity == 7


# --- Portfolio ---------------------------------------------------------------

def test_portfolio_fill_to_trade_r_and_cash_conservation():
    pf = Portfolio(starting_cash=10_000.0)
    entry_order = Order("AAA", Direction.LONG, SignalKind.ENTRY, OrderType.MARKET, 10, None, 90.0, 10.0)
    pf.apply_entry(Fill("AAA", date(2020, 1, 2), 100.0, 10, Direction.LONG, FillKind.ENTRY), entry_order)
    assert pf.cash == pytest.approx(9_000.0)  # 10 * 100
    pf.apply_exit(Fill("AAA", date(2020, 1, 6), 120.0, 10, Direction.LONG, FillKind.EXIT))
    assert pf.cash == pytest.approx(10_200.0)
    (trade,) = pf.trades
    assert trade.r_multiple == pytest.approx(2.0)  # (120-100)/(100-90)
    assert trade.pnl == pytest.approx(200.0)
    assert trade.initial_stop == pytest.approx(90.0)


def test_portfolio_exit_without_lot_is_noop():
    pf = Portfolio(starting_cash=100.0)
    pf.apply_exit(Fill("AAA", date(2020, 1, 2), 100.0, 10, Direction.LONG, FillKind.EXIT))
    assert pf.trades == [] and pf.cash == pytest.approx(100.0)


# --- compute_metrics ---------------------------------------------------------

def _trade(r, pnl):
    return Trade("AAA", Direction.LONG, date(2020, 1, 1), 100.0, date(2020, 1, 2), 110.0,
                 10, 90.0, r, pnl, Regime.UNKNOWN)


def test_metrics_expectancy_and_profit_factor():
    trades = [_trade(2.0, 200.0), _trade(2.0, 200.0), _trade(-1.0, -100.0)]
    eq = pd.Series([100.0, 120.0, 90.0], index=pd.DatetimeIndex(
        [date(2020, 1, 1), date(2020, 1, 2), date(2020, 1, 3)]))
    m = compute_metrics(trades, eq)
    assert m.num_trades == 3
    assert m.win_rate == pytest.approx(2 / 3)
    assert m.expectancy == pytest.approx(2 / 3 * 2.0 - 1 / 3 * 1.0)
    assert m.profit_factor == pytest.approx(400.0 / 100.0)
    assert m.max_drawdown_pct == pytest.approx((120.0 - 90.0) / 120.0)


def test_metrics_empty_trades():
    eq = pd.Series([100.0, 100.0], index=pd.DatetimeIndex([date(2020, 1, 1), date(2020, 1, 2)]))
    m = compute_metrics([], eq)
    assert m.num_trades == 0 and m.profit_factor == 0.0 and m.expectancy == 0.0
