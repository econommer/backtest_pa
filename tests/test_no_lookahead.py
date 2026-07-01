"""The milestone's defining invariant: no look-ahead (design spec §8.1)."""
from __future__ import annotations

from datetime import date

from btf.broker.simple_broker import SimpleBroker
from btf.context.context import Context
from btf.core import Signal
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold
from tests.m1_fixtures import uptrend_provider


class SpyStrategy:
    """Buy-and-hold that asserts the firewall on every bar and records signal timing."""

    def __init__(self) -> None:
        self.name = "spy"
        self.warmup_bars = 0
        self._inner = BuyAndHold(nominal_stop_pct=0.5)
        self.entry_as_of: dict[str, date] = {}

    def on_bar(self, ctx: Context) -> list[Signal]:
        for sym in ctx.universe:
            hist = ctx.history(sym)
            if len(hist):
                assert max(hist.index).date() == ctx.as_of, "history leaked a future bar"
            bar = ctx.bar(sym)
            if bar is not None:
                assert bar.ts == ctx.as_of, "bar() returned a non-as_of bar"
        signals = self._inner.on_bar(ctx)
        for sig in signals:
            self.entry_as_of[sig.symbol] = ctx.as_of
        return signals


def test_no_lookahead_invariant_and_entry_strictly_after_signal():
    prov = uptrend_provider("AAA", days=10)
    spy = SpyStrategy()
    result = BasicEngine().run(
        strategy=spy,
        data=prov,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 10), "starting_cash": 100_000.0},
    )
    assert result.trades, "expected at least one trade"
    for trade in result.trades:
        signalled_on = spy.entry_as_of[trade.symbol]
        assert trade.entry_ts > signalled_on, "entry filled no later than its own signal bar"
