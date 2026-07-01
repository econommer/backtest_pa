"""Execution / broker model interface.

Simulates fills with slippage and commission, and models gap-through stops:
a gap that jumps a stop fills at the open, not the stop price (gap-risk).
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from btf.core import Bar, Fill, Order, Position


@runtime_checkable
class Broker(Protocol):
    """Turns Orders and stop conditions into simulated Fills."""

    def execute(self, orders: list[Order], bars: Mapping[str, Bar]) -> list[Fill]:
        """Fill pending orders against the execution bar (slippage + commission)."""
        ...

    def sweep_stops(self, positions: Mapping[str, Position], bars: Mapping[str, Bar]) -> list[Fill]:
        """Check each position's stop against ``bars``; gap-through fills at the open."""
        ...
