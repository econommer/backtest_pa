"""Position sizing / risk interface.

Converts strategy Signals into sized Orders using the brain formula
size = R$ / stop_distance (expectancy-and-position-sizing), subject to
per-trade risk %, portfolio heat, and max-position limits.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from btf.context.context import Context
from btf.core import Order, Signal


@runtime_checkable
class PositionSizer(Protocol):
    """Turns intentions into sized orders. Owns cash/heat/max-position rules."""

    def size(self, signals: list[Signal], ctx: Context) -> list[Order]:
        """Return sized Orders for the given Signals (some may be dropped)."""
        ...
