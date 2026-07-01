"""``SimpleBroker`` — trivial next-open MARKET fills + gap-through stop sweep.

Costs are plumbed but default to zero (M1 runs at zero). Long-only; short side and
non-MARKET order types are out of M1 scope. See M1 design spec §5.2.
"""
from __future__ import annotations

from typing import Mapping

from btf.core import Bar, Direction, Fill, FillKind, Order, OrderType, Position, SignalKind

_ENTRY_KINDS = (SignalKind.ENTRY, SignalKind.ADD)


class SimpleBroker:
    """Fills MARKET orders at the bar open (± slippage) and sweeps resting stops."""

    def __init__(self, commission_per_share: float = 0.0, slippage_pct: float = 0.0) -> None:
        self.commission_per_share = commission_per_share
        self.slippage_pct = slippage_pct

    def execute(self, orders: list[Order], bars: Mapping[str, Bar]) -> list[Fill]:
        fills: list[Fill] = []
        for order in orders:
            if order.order_type is not OrderType.MARKET:
                # Fail loudly so a future non-MARKET strategy can't silently no-op.
                raise NotImplementedError(
                    f"SimpleBroker (M1) only fills MARKET orders, got {order.order_type}"
                )
            bar = bars.get(order.symbol)
            if bar is None:
                continue
            is_buy = order.kind in _ENTRY_KINDS
            price = bar.open * (1 + self.slippage_pct) if is_buy else bar.open * (1 - self.slippage_pct)
            commission = self.commission_per_share * order.quantity
            fills.append(
                Fill(
                    symbol=order.symbol,
                    ts=bar.ts,
                    price=price,
                    quantity=order.quantity,
                    direction=order.direction,
                    kind=FillKind.ENTRY if is_buy else FillKind.EXIT,
                    commission=commission,
                    slippage=abs(price - bar.open) * order.quantity,
                    reason=order.reason,
                )
            )
        return fills

    def sweep_stops(self, positions: Mapping[str, Position], bars: Mapping[str, Bar]) -> list[Fill]:
        fills: list[Fill] = []
        for sym, pos in positions.items():
            if pos.direction is not Direction.LONG or pos.stop_price is None:
                continue
            bar = bars.get(sym)
            if bar is None or bar.low > pos.stop_price:
                continue
            # Gap-through: if the bar opened below the stop, we fill worse — at the open.
            price = bar.open if bar.open < pos.stop_price else pos.stop_price
            commission = self.commission_per_share * pos.quantity
            fills.append(
                Fill(
                    symbol=sym,
                    ts=bar.ts,
                    price=price,
                    quantity=pos.quantity,
                    direction=pos.direction,
                    kind=FillKind.STOP_OUT,
                    commission=commission,
                    slippage=0.0,
                    reason="stop-out",
                )
            )
        return fills
