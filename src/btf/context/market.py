"""Market regime / breadth snapshot (situation-awareness).

Reusable across strategies as an entry gate ("trade only with a tailwind").
Belongs to no single strategy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from btf.core import Regime


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Point-in-time market state handed to the strategy inside Context."""

    as_of: date
    regime: Regime
    index_trend: float | None = None
    breadth: float | None = None
    meta: dict[str, object] = field(default_factory=dict)
