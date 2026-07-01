#!/usr/bin/env python3
"""Real-data buy-and-hold across three asset classes — Index / Equities / Commodity.

A hands-on demo of the Phase-1 pipeline end-to-end on **real Yahoo Finance data**:
fetch -> normalise -> parquet cache -> BasicEngine run -> metrics. Because the only
strategy wired up so far is ``BuyAndHold`` (VCP is milestone M4, not built yet), this
compares what each asset class *did* over the window, not a trading edge.

Two numbers per universe:
  * **Equal-weight basket** buy&hold return, computed straight from adjusted closes
    (the intuitive "what the basket did"); and
  * an **engine run** (``BuyAndHold`` through ``BasicEngine``) that proves the books
    reconcile end-to-end and produces an SPY benchmark overlay.

Usage (needs network on first run; cached to ./data_cache afterwards):

    pip install -e '.[data]'
    python scripts/run_asset_classes.py
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from btf.broker.simple_broker import SimpleBroker
from btf.data.yfinance_provider import YFinanceDataProvider
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold

START = date(2015, 1, 1)
END = date(2025, 1, 1)
BENCHMARK = "SPY"          # common yardstick so the three lines are comparable
STARTING_CASH = 100_000.0
CACHE_DIR = "data_cache"


@dataclass(frozen=True)
class Universe:
    name: str
    note: str
    symbols: list[str]


UNIVERSES = [
    Universe(
        "Index", "broad-market ETFs (S&P500 / Nasdaq100 / Dow / Russell2000)",
        ["SPY", "QQQ", "DIA", "IWM"],
    ),
    Universe(
        "Equities", "sector-spread US large caps",
        ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ"],
    ),
    Universe(
        "Commodity", "commodity ETFs (gold / silver / oil / broad / nat-gas)",
        ["GLD", "SLV", "USO", "DBC", "UNG"],
    ),
]


def equal_weight_curve(history: pd.DataFrame, symbols: list[str]) -> pd.Series:
    """Normalised equal-weight buy&hold curve from a MultiIndex(symbol,ts) history."""
    closes = history["close"].unstack("symbol").reindex(columns=symbols).sort_index()
    closes = closes.ffill()
    # Start only once every name has printed a price (avoids a fake early spike).
    start = closes.dropna().index.min()
    closes = closes.loc[start:].dropna(how="any")
    normed = closes.divide(closes.iloc[0])          # each name -> 1.0 at start
    return normed.mean(axis=1)                       # equal weight across names


def max_drawdown_pct(curve: pd.Series) -> float:
    return float(((curve.cummax() - curve) / curve.cummax()).max())


def cagr(curve: pd.Series) -> float:
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    return float(curve.iloc[-1] / curve.iloc[0]) ** (1 / years) - 1


def run_universe(u: Universe) -> dict[str, object]:
    provider = YFinanceDataProvider(
        u.symbols, START, END, cache_dir=CACHE_DIR, benchmark_symbol=BENCHMARK,
    )
    history = provider.history(u.symbols, START, END)

    # --- headline: equal-weight basket buy&hold (independent of sizer quirks) -----
    ew = equal_weight_curve(history, u.symbols)

    # --- pipeline proof: full engine run, books must reconcile --------------------
    result = BasicEngine().run(
        strategy=BuyAndHold(nominal_stop_pct=0.9),   # far stop -> hold, never stopped
        data=provider,
        broker=SimpleBroker(commission_per_share=0.005, slippage_pct=0.0005),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={
            "start": START, "end": END, "starting_cash": STARTING_CASH,
            "symbols": u.symbols, "benchmark": BENCHMARK,
        },
    )
    eq = result.equity_curve
    total_pnl = sum(t.pnl for t in result.trades)
    reconciles = abs(STARTING_CASH + total_pnl - float(eq.iloc[-1])) < 1e-4

    return {
        "universe": u,
        "ew_total_return": ew.iloc[-1] - 1.0,
        "ew_cagr": cagr(ew),
        "ew_max_dd": max_drawdown_pct(ew),
        "engine_final": float(eq.iloc[-1]),
        "engine_trades": len(result.trades),
        "engine_reconciles": reconciles,
        "bench_final": float(result.benchmark_curve.iloc[-1]),
        "start": ew.index[0].date(),
        "end": ew.index[-1].date(),
    }


def main() -> int:
    print(f"Real-data buy&hold  {START} .. {END}   benchmark={BENCHMARK}\n")
    rows = [run_universe(u) for u in UNIVERSES]

    print(f"{'Asset class':<11} {'Symbols':<28} {'EW ret':>8} {'CAGR':>7} "
          f"{'MaxDD':>7} {'Books':>6}")
    print("-" * 74)
    for r in rows:
        u: Universe = r["universe"]  # type: ignore[assignment]
        print(f"{u.name:<11} {','.join(u.symbols):<28} "
              f"{r['ew_total_return']:>7.0%} {r['ew_cagr']:>6.1%} "
              f"{r['ew_max_dd']:>6.0%} {'ok' if r['engine_reconciles'] else 'FAIL':>6}")

    b = rows[0]["bench_final"]
    print("-" * 74)
    print(f"SPY benchmark buy&hold of ${STARTING_CASH:,.0f}  ->  ${b:,.0f} "
          f"({b / STARTING_CASH - 1:.0%})   window {rows[0]['start']}..{rows[0]['end']}")
    print("\n[!] SURVIVORSHIP / SELECTION BIAS: hand-picked, currently-listed symbols; "
          "no delisted names. Phase-1 numbers are upward-biased - see BACKTESTING_PLAN.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
