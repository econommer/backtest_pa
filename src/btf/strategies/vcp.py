"""``VcpStrategy`` — Minervini's Volatility Contraction Pattern breakout (M4).

Mechanizes the brain setup ``wiki/setups/vcp-breakout.md`` and BACKTESTING_PLAN §5.
Every gate traces back to a brain page so the rules stay auditable:

1. **Stage-2 trend filter** — ``close > SMA150`` and SMA150 rising (Stan Weinstein
   Stage 2). Brain: ``market-structure``, ``stan-weinstein``.
2. **Relative strength** — cross-sectional ROC-rank percentile ≥ threshold. A faithful
   Phase-1 approximation of IBD RS via whole-universe ROC ranking (Decision #3;
   brain ``relative-strength``). Industry RS is deferred to Phase 2.
3. **Contraction** — the recent tight window's range (and volume) shrinks vs the prior
   window: the 2–4 step "27→17→8" narrowing. Brain: ``volatility-contraction``.
4. **Tight build-up hugging resistance** — the last window is a narrow range under the
   pivot. Brain: ``support-and-resistance``.
5. **Pivot / breakout** — pivot = prior resistance (base-window high); a *close above
   the pivot on volume expansion* confirms the breakout. Fill is next-open (the engine
   decides on bar *t*'s close, fills at *t+1*'s open — the plan's allowed fill model,
   and what ``SimpleBroker`` supports).
6. **Initial stop** — support − k·ATR, never sitting exactly on support (leaves room for
   a shakeout). Rides as a resting stop the broker sweeps. Brain:
   ``initial-stop-and-r-multiple``, ``gap-risk``.
7. **Trailing exit** — exit when ``close < SMA50`` (medium-term trail). Brain:
   ``trailing-stops``. (Distribution-day exits are deferred — kept minimal for v1.)

Long-only. Pure detector functions are module-level so they are unit-testable in
isolation; ``VcpStrategy`` composes them and speaks only ``Signal`` (Strategy ⟂ Engine).
"""
from __future__ import annotations

import pandas as pd

from btf.context.context import Context
from btf.core import Direction, OrderType, Signal, SignalKind


# --------------------------------------------------------------------------- #
# pure detectors (operate on an OHLCV frame with a sorted DatetimeIndex)
# --------------------------------------------------------------------------- #
def sma(series: pd.Series, n: int) -> float | None:
    """Last value of the ``n``-bar simple moving average, or None if too short."""
    if len(series) < n:
        return None
    return float(series.iloc[-n:].mean())


def atr(df: pd.DataFrame, period: int) -> float | None:
    """Average True Range over the last ``period`` bars (simple mean), or None."""
    if len(df) < period + 1:
        return None
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    prev_close = df["close"].shift(1).to_numpy(dtype=float)
    tr = []
    for i in range(1, len(df)):
        tr.append(
            max(high[i] - low[i], abs(high[i] - prev_close[i]), abs(low[i] - prev_close[i]))
        )
    return float(sum(tr[-period:]) / period)


def roc(series: pd.Series, lookback: int) -> float | None:
    """Rate of change over ``lookback`` bars (``last / lookback-ago − 1``), or None."""
    if len(series) < lookback + 1:
        return None
    past = float(series.iloc[-1 - lookback])
    if past == 0:
        return None
    return float(series.iloc[-1]) / past - 1.0


def in_stage2(df: pd.DataFrame, trend_ma: int = 150, slope_lookback: int = 20) -> bool:
    """Stage-2: last close above a *rising* long MA."""
    closes = df["close"]
    if len(closes) < trend_ma + slope_lookback:
        return False
    sma_now = float(closes.iloc[-trend_ma:].mean())
    sma_prev = float(closes.iloc[-(trend_ma + slope_lookback) : -slope_lookback].mean())
    return float(closes.iloc[-1]) > sma_now and sma_now > sma_prev


def pivot_price(df: pd.DataFrame, base_window: int = 30) -> float | None:
    """Prior resistance = highest high over ``base_window`` bars ending *yesterday*."""
    if len(df) < base_window + 1:
        return None
    return float(df["high"].iloc[-(base_window + 1) : -1].max())


def is_tight(df: pd.DataFrame, tight_window: int = 10, max_tightness: float = 0.10) -> bool:
    """The build-up window (ending yesterday) spans ≤ ``max_tightness`` of price."""
    if len(df) < tight_window + 1:
        return False
    window = df.iloc[-(tight_window + 1) : -1]
    last_close = float(df["close"].iloc[-1])
    if last_close <= 0:
        return False
    span = float(window["high"].max() - window["low"].min())
    return span / last_close <= max_tightness


def is_contraction(
    df: pd.DataFrame,
    tight_window: int = 10,
    range_ratio: float = 0.7,
    require_volume: bool = True,
) -> bool:
    """Recent window's range (and volume) contracts vs the immediately prior window."""
    if len(df) < 2 * tight_window + 1:
        return False
    recent = df.iloc[-(tight_window + 1) : -1]
    prior = df.iloc[-(2 * tight_window + 1) : -(tight_window + 1)]
    prior_range = float(prior["high"].max() - prior["low"].min())
    if prior_range <= 0:
        return False
    recent_range = float(recent["high"].max() - recent["low"].min())
    if recent_range > range_ratio * prior_range:
        return False
    if require_volume:
        return float(recent["volume"].mean()) <= float(prior["volume"].mean())
    return True


def is_breakout(
    df: pd.DataFrame, pivot: float | None, vol_window: int = 30, vol_expansion: float = 1.3
) -> bool:
    """Today closes above the pivot on above-average (expanding) volume."""
    if pivot is None or len(df) < vol_window + 1:
        return False
    today = df.iloc[-1]
    if float(today["close"]) <= pivot:
        return False
    avg_vol = float(df["volume"].iloc[-(vol_window + 1) : -1].mean())
    return float(today["volume"]) >= vol_expansion * avg_vol


def initial_stop(
    df: pd.DataFrame, tight_window: int = 10, atr_period: int = 14, k: float = 1.0
) -> float | None:
    """Support (build-up low) minus ``k``·ATR — never sitting on support."""
    if len(df) < tight_window + 1:
        return None
    a = atr(df, atr_period)
    if a is None:
        return None
    support = float(df["low"].iloc[-(tight_window + 1) : -1].min())
    return support - k * a


# --------------------------------------------------------------------------- #
# strategy
# --------------------------------------------------------------------------- #
class VcpStrategy:
    """Emits VCP breakout ENTRY and trailing-MA EXIT signals; knows nothing about fills."""

    def __init__(
        self,
        trend_ma: int = 150,
        slope_lookback: int = 20,
        rs_lookback: int = 126,
        rs_min_percentile: float = 0.70,
        base_window: int = 30,
        tight_window: int = 10,
        max_tightness: float = 0.10,
        range_ratio: float = 0.7,
        vol_expansion: float = 1.3,
        atr_period: int = 14,
        stop_atr_mult: float = 1.0,
        trail_ma: int = 50,
        require_rs: bool = True,
    ) -> None:
        self.name = "vcp"
        self.trend_ma = trend_ma
        self.slope_lookback = slope_lookback
        self.rs_lookback = rs_lookback
        self.rs_min_percentile = rs_min_percentile
        self.base_window = base_window
        self.tight_window = tight_window
        self.max_tightness = max_tightness
        self.range_ratio = range_ratio
        self.vol_expansion = vol_expansion
        self.atr_period = atr_period
        self.stop_atr_mult = stop_atr_mult
        self.trail_ma = trail_ma
        self.require_rs = require_rs
        # Enough history for the slowest gate (rising SMA150) before we can compute.
        self.warmup_bars = trend_ma + slope_lookback

    def on_bar(self, ctx: Context) -> list[Signal]:
        signals: list[Signal] = []
        rs = self._rs_percentiles(ctx)
        universe = list(ctx.universe)
        # PIT universe (M6): a held stock may have left the index — keep
        # managing its exit; only NEW entries are restricted to members.
        held_outside = [s for s in ctx.positions if s not in set(universe)]
        for sym in [*universe, *held_outside]:
            df = ctx.history(sym)
            if len(df) == 0:
                continue
            if sym in ctx.positions:
                exit_sig = self._exit_signal(sym, df)
                if exit_sig is not None:
                    signals.append(exit_sig)
                continue
            entry_sig = self._entry_signal(sym, df, rs)
            if entry_sig is not None:
                signals.append(entry_sig)
        return signals

    # ---- exits ---------------------------------------------------------------
    def _exit_signal(self, sym: str, df: pd.DataFrame) -> Signal | None:
        trail = sma(df["close"], self.trail_ma)
        if trail is None or float(df["close"].iloc[-1]) >= trail:
            return None
        return Signal(
            symbol=sym,
            kind=SignalKind.EXIT,
            direction=Direction.LONG,
            order_type=OrderType.MARKET,
            reason=f"vcp trail-MA{self.trail_ma} exit",
        )

    # ---- entries -------------------------------------------------------------
    def _entry_signal(self, sym: str, df: pd.DataFrame, rs: dict[str, float]) -> Signal | None:
        if not in_stage2(df, self.trend_ma, self.slope_lookback):
            return None
        if self.require_rs:
            pct = rs.get(sym)
            if pct is None or pct < self.rs_min_percentile:
                return None
        if not is_contraction(df, self.tight_window, self.range_ratio):
            return None
        if not is_tight(df, self.tight_window, self.max_tightness):
            return None
        pivot = pivot_price(df, self.base_window)
        if not is_breakout(df, pivot, self.base_window, self.vol_expansion):
            return None
        stop = initial_stop(df, self.tight_window, self.atr_period, self.stop_atr_mult)
        if stop is None or stop >= float(df["close"].iloc[-1]):
            return None
        return Signal(
            symbol=sym,
            kind=SignalKind.ENTRY,
            direction=Direction.LONG,
            order_type=OrderType.MARKET,
            trigger_price=pivot,
            stop_price=stop,
            reason="vcp breakout",
            meta={"pivot": pivot, "rs_pct": rs.get(sym)},
        )

    # ---- relative strength ---------------------------------------------------
    def _rs_percentiles(self, ctx: Context) -> dict[str, float]:
        """Whole-universe ROC ranking → percentile per symbol (IBD-RS approximation)."""
        rocs: dict[str, float] = {}
        for sym in ctx.universe:
            df = ctx.history(sym)
            if len(df) == 0:
                continue
            r = roc(df["close"], self.rs_lookback)
            if r is not None:
                rocs[sym] = r
        if not rocs:
            return {}
        values = list(rocs.values())
        n = len(values)
        return {sym: sum(1 for v in values if v <= r) / n for sym, r in rocs.items()}
