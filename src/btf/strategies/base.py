"""Strategy interface — emits *intentions* only, never touches cash or fills.

A strategy sees the world only through Context (data <= as_of), enforcing the
Strategy-perpendicular-Engine principle (code/CLAUDE.md).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from btf.context.context import Context
from btf.core import Signal


@runtime_checkable
class Strategy(Protocol):
    """Produces Signals from a per-bar Context. Knows nothing about execution."""

    name: str
    warmup_bars: int  # history needed before it can compute (MA200, ATR, ...)

    def on_bar(self, ctx: Context) -> list[Signal]:
        """Return the strategy's intentions for the current bar (may be empty)."""
        ...
