"""Stop-out path: a gap-through fires a resting stop (design spec §8.3)."""
from __future__ import annotations

from datetime import date

from btf.broker.simple_broker import SimpleBroker
from btf.context.context import Context
from btf.core import Direction, OrderType, Signal, SignalKind
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from tests.m1_fixtures import gap_through_provider


class TightStopEntry:
    """Enters AAA once on bar 1 with a tight stop just below the early up-trend."""

    def __init__(self, stop_price: float) -> None:
        self.name = "tight-stop"
        self.warmup_bars = 0
        self.stop_price = stop_price
        self._entered = False

    def on_bar(self, ctx: Context) -> list[Signal]:
        if self._entered or ctx.bar("AAA") is None or "AAA" in ctx.positions:
            return []
        self._entered = True
        return [Signal("AAA", SignalKind.ENTRY, Direction.LONG, OrderType.MARKET,
                       None, self.stop_price, reason="tight entry")]


def test_gap_through_stop_out_negative_r():
    # Entry fills at bar 2 open (101); stop at 99. Bar 4 gaps to open 70 (< 99) → STOP_OUT @ 70.
    result = BasicEngine().run(
        strategy=TightStopEntry(stop_price=99.0),
        data=gap_through_provider("AAA"),
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.05),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 6), "starting_cash": 100_000.0},
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_price == 70.0            # gapped open, worse than the 99 stop
    assert trade.exit_ts == date(2020, 1, 4)
    assert trade.initial_stop == 99.0
    assert trade.r_multiple < 0                 # a loss
    assert trade.reason_exit == "stop-out"
