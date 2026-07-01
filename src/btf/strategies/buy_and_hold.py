"""``BuyAndHold`` — dummy strategy (implements Strategy) for M1 plumbing.

Buys each universe symbol once with a MARKET entry and a nominal (far-away) stop,
then holds to liquidation — never emits EXIT. The stop is a plumbing device so
R-based sizing is well-defined; on the fake up-trending data it never triggers.
See M1 design spec §5.4.
"""
from __future__ import annotations

from btf.context.context import Context
from btf.core import Direction, OrderType, Signal, SignalKind


class BuyAndHold:
    """Enter every symbol once; hold. Knows nothing about execution or sizing."""

    def __init__(self, nominal_stop_pct: float = 0.5) -> None:
        self.name = "buy-and-hold"
        self.warmup_bars = 0
        self.nominal_stop_pct = nominal_stop_pct
        self._entered: set[str] = set()

    def on_bar(self, ctx: Context) -> list[Signal]:
        signals: list[Signal] = []
        for sym in ctx.universe:
            if sym in self._entered or sym in ctx.positions:
                continue
            bar = ctx.bar(sym)
            if bar is None:
                continue
            signals.append(
                Signal(
                    symbol=sym,
                    kind=SignalKind.ENTRY,
                    direction=Direction.LONG,
                    order_type=OrderType.MARKET,
                    trigger_price=None,
                    stop_price=bar.close * (1 - self.nominal_stop_pct),
                    reason="buy-and-hold entry",
                )
            )
            self._entered.add(sym)
        return signals
