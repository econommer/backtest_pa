"""Internal portfolio bookkeeping — cash, open lots, equity curve, closed Trades.

Not part of the frozen M0 contract; owned by ``BasicEngine``. Applies broker
``Fill``s to the book and assembles closed ``Trade``s in R units. See M1 design
spec §5.5.

The frozen ``Fill`` carries no stop field, so ``apply_entry`` takes the originating
entry ``Order`` explicitly to recover ``stop_price`` / ``risk_per_share``; from then
on those live on the internal lot and exits need no order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from btf.core import Direction, Fill, Order, Position, Regime, Trade


@dataclass
class _OpenLot:
    symbol: str
    quantity: int
    entry_price: float
    stop_price: float
    entry_ts: date
    risk_per_share: float
    cost_paid: float
    reason_entry: str
    direction: Direction


class Portfolio:
    """Mutable book: cash, one open lot per symbol (M1), equity curve, closed trades."""

    def __init__(self, starting_cash: float) -> None:
        self.cash: float = float(starting_cash)
        self._lots: dict[str, _OpenLot] = {}
        self.equity_curve: list[tuple[date, float]] = []
        self.trades: list[Trade] = []

    def apply_entry(self, fill: Fill, order: Order) -> None:
        """Open a lot from an ENTRY fill; debit cash; denominate R by the actual fill."""
        if order.stop_price is None:
            raise ValueError(f"entry order for {fill.symbol} has no stop_price")
        self.cash -= fill.price * fill.quantity + fill.commission
        self._lots[fill.symbol] = _OpenLot(
            symbol=fill.symbol,
            quantity=fill.quantity,
            entry_price=fill.price,
            stop_price=order.stop_price,
            entry_ts=fill.ts,
            risk_per_share=fill.price - order.stop_price,
            cost_paid=fill.commission,
            reason_entry=order.reason,
            direction=order.direction,
        )

    def apply_exit(self, fill: Fill) -> None:
        """Close the lot for ``fill.symbol`` (EXIT / STOP_OUT / liquidation); build a Trade.

        Closing a non-existent lot is a no-op — handles the exit-then-sweep-same-bar case.
        """
        lot = self._lots.pop(fill.symbol, None)
        if lot is None:
            return
        self.cash += fill.price * fill.quantity - fill.commission
        total_costs = lot.cost_paid + fill.commission
        pnl = (fill.price - lot.entry_price) * fill.quantity - total_costs
        r_multiple = (
            (fill.price - lot.entry_price) / lot.risk_per_share
            if lot.risk_per_share > 0
            else 0.0
        )
        self.trades.append(
            Trade(
                symbol=lot.symbol,
                direction=lot.direction,
                entry_ts=lot.entry_ts,
                entry_price=lot.entry_price,
                exit_ts=fill.ts,
                exit_price=fill.price,
                quantity=fill.quantity,
                initial_stop=lot.stop_price,
                r_multiple=r_multiple,
                pnl=pnl,
                regime=Regime.UNKNOWN,
                reason_entry=lot.reason_entry,
                reason_exit=fill.reason,
            )
        )

    def snapshot_positions(self) -> dict[str, Position]:
        """Read-only Position snapshots for the strategy / stop sweep."""
        return {
            sym: Position(
                symbol=lot.symbol,
                direction=lot.direction,
                quantity=lot.quantity,
                avg_price=lot.entry_price,
                stop_price=lot.stop_price,
                entry_ts=lot.entry_ts,
                risk_per_share=lot.risk_per_share,
            )
            for sym, lot in self._lots.items()
        }

    def mark(self, closes: Mapping[str, float]) -> float:
        """Mark-to-market: equity = cash + Σ qty·close over open lots."""
        held = sum(lot.quantity * closes[sym] for sym, lot in self._lots.items() if sym in closes)
        return self.cash + held

    def record_equity(self, on: date, equity: float) -> None:
        self.equity_curve.append((on, equity))

    def open_symbols(self) -> list[str]:
        return list(self._lots)
