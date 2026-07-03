"""Stop-out path: a gap-through fires a resting stop (design spec §8.3)."""
from __future__ import annotations

from datetime import date

from btf.broker.simple_broker import SimpleBroker
from btf.context.context import Context
from btf.core import Direction, OrderType, Signal, SignalKind
from btf.data.memory_provider import InMemoryDataProvider
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from tests.m1_fixtures import gap_through_provider, make_frame


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


def _delisting_provider(last_aaa_day: int, total_days: int, gap_day: int | None = None) -> InMemoryDataProvider:
    """AAA trades days 1..``last_aaa_day`` then vanishes (delisted); BBB trades the
    full window so the trading calendar keeps advancing past AAA's last bar. AAA's
    stop is set far below its price range so it never sweeps out on its own —
    isolating the delisting-exit path. If ``gap_day`` is given, AAA additionally
    has a hole on that day (no bar) while still trading before and after it —
    a temporary gap, not a delisting.
    """
    dates = [date(2020, 1, d) for d in range(1, total_days + 1)]
    aaa_dates = [d for i, d in enumerate(dates, start=1) if i <= last_aaa_day and i != gap_day]
    opens = [100.0 + i for i in range(len(aaa_dates))]
    closes = [100.5 + i for i in range(len(aaa_dates))]
    highs = [c + 1.0 for c in closes]
    lows = [o - 1.0 for o in opens]
    aaa_frame = make_frame(aaa_dates, opens, highs, lows, closes)

    bbb_opens = [50.0 + 0.1 * i for i in range(total_days)]
    bbb_closes = [50.1 + 0.1 * i for i in range(total_days)]
    bbb_highs = [c + 1.0 for c in bbb_closes]
    bbb_lows = [o - 1.0 for o in bbb_opens]
    bbb_frame = make_frame(dates, bbb_opens, bbb_highs, bbb_lows, bbb_closes)

    return InMemoryDataProvider({"AAA": aaa_frame, "BBB": bbb_frame})


class EntersOnceThenHolds:
    """Enters AAA on the first available bar with a stop far out of reach."""

    def __init__(self, symbol: str = "AAA", stop_price: float = 1.0) -> None:
        self.name = "enter-and-hold"
        self.warmup_bars = 0
        self.symbol = symbol
        self.stop_price = stop_price
        self._entered = False

    def on_bar(self, ctx: Context) -> list[Signal]:
        if self._entered or ctx.bar(self.symbol) is None or self.symbol in ctx.positions:
            return []
        self._entered = True
        return [Signal(self.symbol, SignalKind.ENTRY, Direction.LONG, OrderType.MARKET,
                       None, self.stop_price, reason="enter and hold")]


def test_delisted_while_held_exits_at_last_close_no_equity_cliff():
    # AAA trades days 1-4 then vanishes (delisted). BBB trades the full 8 days,
    # keeping the calendar alive past the delisting. Entry fills day-2 open;
    # AAA's last close is on day 4.
    data = _delisting_provider(last_aaa_day=4, total_days=8)
    result = BasicEngine().run(
        strategy=EntersOnceThenHolds(stop_price=1.0),
        data=data,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.05),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 8), "starting_cash": 100_000.0},
    )
    aaa_trades = [t for t in result.trades if t.symbol == "AAA"]
    assert len(aaa_trades) == 1
    trade = aaa_trades[0]
    # Exits at (or just after) the delisting day, at AAA's last available close.
    assert trade.exit_ts >= date(2020, 1, 4)
    assert trade.exit_price == 103.5  # last AAA close (day 4, per _delisting_provider)
    assert trade.reason_exit != "final liquidation"  # freed mid-run, not at the tail

    # No phantom equity cliff: day-over-day equity change must stay bounded —
    # a real full-position drop (quantity * close) would dwarf this.
    curve = result.equity_curve
    diffs = curve.diff().dropna().abs()
    assert diffs.max() < 5000  # generous bound; a phantom drop would be ~ qty * price (tens of k)


def test_one_day_bar_gap_does_not_liquidate_and_equity_stays_smooth():
    # AAA has a one-day hole (no bar) on day 4 but resumes trading after —
    # a data gap, not a delisting. Must NOT trigger a synthetic exit.
    data = _delisting_provider(last_aaa_day=8, total_days=8, gap_day=4)
    result = BasicEngine().run(
        strategy=EntersOnceThenHolds(stop_price=1.0),
        data=data,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.05),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 8), "starting_cash": 100_000.0},
    )
    aaa_trades = [t for t in result.trades if t.symbol == "AAA"]
    # Only the end-of-run forced liquidation closes it out — no premature exit on the gap day.
    assert len(aaa_trades) == 1
    assert aaa_trades[0].reason_exit == "final liquidation"

    curve = result.equity_curve
    diffs = curve.diff().dropna().abs()
    assert diffs.max() < 5000  # the gap day must not phantom-drop equity to cash-only
