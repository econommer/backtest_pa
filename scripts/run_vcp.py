#!/usr/bin/env python3
"""First VCP backtest on real data — Index / Equities / Commodity (M4).

Runs the mechanized ``VcpStrategy`` (wiki/setups/vcp-breakout.md) through the engine
on live Yahoo Finance data and prints the brain's backtest-notes metrics in R units
(win rate, avg win/loss R, expectancy, max streak, max drawdown, profit factor).

VCP is a US-equity momentum setup; running it on the index/commodity ETF baskets is a
deliberate cross-check — you *expect* far fewer clean setups there, and that shows up
in the trade count. RS is the whole-universe ROC approximation (Phase-1, Decision #3).

Usage (network on first run; cached to ./data_cache afterwards):

    pip install -e '.[data]'
    python scripts/run_vcp.py
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from btf.broker.simple_broker import SimpleBroker
from btf.data.yfinance_provider import YFinanceDataProvider
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.vcp import VcpStrategy

START = date(2015, 1, 1)
END = date(2025, 1, 1)
BENCHMARK = "SPY"
STARTING_CASH = 100_000.0
CACHE_DIR = "data_cache"


@dataclass(frozen=True)
class Universe:
    name: str
    symbols: list[str]


UNIVERSES = [
    Universe("Index", [
        "SPY", "QQQ", "DIA", "IWM", "MDY", "XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP",
    ]),
    Universe("Equities", [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "JPM", "V",
        "MA", "UNH", "JNJ", "XOM", "CVX", "HD", "PG", "KO", "PEP", "COST",
        "WMT", "DIS", "NFLX", "AMD", "CRM", "ADBE", "ORCL", "CSCO", "INTC", "QCOM",
    ]),
    Universe("Commodity", [
        "GLD", "SLV", "USO", "DBC", "UNG", "GDX", "DBA", "CORN", "WEAT", "PPLT",
    ]),
]


def run_universe(u: Universe) -> dict[str, object]:
    provider = YFinanceDataProvider(
        u.symbols, START, END, cache_dir=CACHE_DIR, benchmark_symbol=BENCHMARK,
    )
    result = BasicEngine().run(
        strategy=VcpStrategy(),
        data=provider,
        broker=SimpleBroker(commission_per_share=0.005, slippage_pct=0.0005),
        sizer=FixedRiskSizer(risk_pct=0.01),
        config={
            "start": START, "end": END, "starting_cash": STARTING_CASH,
            "symbols": u.symbols, "benchmark": BENCHMARK,
        },
    )
    m = result.metrics
    total_pnl = sum(t.pnl for t in result.trades)
    return {
        "name": u.name,
        "n_syms": len(u.symbols),
        "metrics": m,
        "final": float(result.equity_curve.iloc[-1]),
        "reconciles": abs(STARTING_CASH + total_pnl - float(result.equity_curve.iloc[-1])) < 1e-4,
    }


def main() -> int:
    print(f"VCP backtest  {START} .. {END}   RS=universe-ROC   risk=1%/trade\n")
    rows = [run_universe(u) for u in UNIVERSES]

    hdr = (f"{'Asset class':<11} {'Syms':>4} {'Trades':>6} {'Win%':>6} "
           f"{'AvgW':>6} {'AvgL':>6} {'Expect':>7} {'PF':>5} {'MaxDD':>6} {'Final$':>10}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        m = r["metrics"]  # type: ignore[assignment]
        print(f"{r['name']:<11} {r['n_syms']:>4} {m.num_trades:>6} "
              f"{m.win_rate:>5.0%} {m.avg_win_r:>5.2f}R {m.avg_loss_r:>5.2f}R "
              f"{m.expectancy:>6.2f}R {m.profit_factor:>5.2f} "
              f"{m.max_drawdown_pct:>5.0%} {r['final']:>10,.0f}")
    print("-" * len(hdr))
    print(f"Books reconcile: {all(r['reconciles'] for r in rows)}   "
          f"(start ${STARTING_CASH:,.0f})")
    print("\n[!] SELECTION / SURVIVORSHIP BIAS (Phase-1): hand-picked, currently-listed "
          "symbols; no delisted names. Expectancy is upward-biased. Small samples (<30 "
          "trades) are not significant. See BACKTESTING_PLAN.md M5/M6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
