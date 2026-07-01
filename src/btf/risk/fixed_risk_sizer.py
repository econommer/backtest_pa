"""``FixedRiskSizer`` — R-based position sizing (implements PositionSizer).

size = floor(risk_pct · equity / stop_distance), capped by a running per-bar cash
budget (expectancy-and-position-sizing). Portfolio heat / max-position limits are
deferred (M1 design spec §5.3, §9).
"""
from __future__ import annotations

from math import floor

from btf.context.context import Context
from btf.core import Direction, Order, OrderType, Signal, SignalKind


class FixedRiskSizer:
    """Turns ENTRY/EXIT signals into MARKET orders sized by fixed fractional risk."""

    def __init__(self, risk_pct: float) -> None:
        self.risk_pct = risk_pct

    def size(self, signals: list[Signal], ctx: Context) -> list[Order]:
        orders: list[Order] = []
        budget = ctx.cash  # running cash budget consumed as entries are sized this bar
        for sig in signals:
            if sig.kind is SignalKind.ENTRY:
                order = self._size_entry(sig, ctx, budget)
                if order is not None:
                    orders.append(order)
                    bar = ctx.bar(sig.symbol)
                    if bar is not None:
                        budget -= order.quantity * bar.close
            elif sig.kind is SignalKind.EXIT:
                order = self._size_exit(sig, ctx)
                if order is not None:
                    orders.append(order)
        return orders

    def _size_entry(self, sig: Signal, ctx: Context, budget: float) -> Order | None:
        bar = ctx.bar(sig.symbol)
        if bar is None or sig.stop_price is None:
            return None
        ref = bar.close
        risk_per_share = ref - sig.stop_price
        if risk_per_share <= 0:
            return None
        qty = floor(self.risk_pct * ctx.equity / risk_per_share)
        if ref > 0:
            qty = min(qty, floor(budget / ref))
        if qty < 1:
            return None
        return Order(
            symbol=sig.symbol,
            direction=Direction.LONG,
            kind=SignalKind.ENTRY,
            order_type=OrderType.MARKET,
            quantity=qty,
            trigger_price=None,
            stop_price=sig.stop_price,
            risk_per_share=risk_per_share,
            reason=sig.reason,
        )

    def _size_exit(self, sig: Signal, ctx: Context) -> Order | None:
        pos = ctx.positions.get(sig.symbol)
        if pos is None or pos.quantity < 1:
            return None
        return Order(
            symbol=sig.symbol,
            direction=pos.direction,
            kind=SignalKind.EXIT,
            order_type=OrderType.MARKET,
            quantity=pos.quantity,
            trigger_price=None,
            stop_price=None,
            risk_per_share=0.0,
            reason=sig.reason,
        )
