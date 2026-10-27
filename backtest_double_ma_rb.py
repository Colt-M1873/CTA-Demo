# -*- coding: utf-8 -*-
"""Simple Double-MA CTA backtest on AKShare RB daily continuous bars."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy_ctastrategy.backtesting import BacktestingEngine
from vnpy_ctastrategy.strategies.double_ma_strategy import DoubleMaStrategy

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
CSV_PATH = BASE / "data" / "RB_daily_main_sina.csv"
STATS_PATH = BASE / "data" / "backtest_double_ma_rb_stats.txt"
EQUITY_PATH = BASE / "data" / "backtest_double_ma_rb_equity.csv"

VT_SYMBOL = "RB99.SHFE"
SYMBOL = "RB99"
EXCHANGE = Exchange.SHFE
GATEWAY = "DB"

FAST_WINDOW = 10
SLOW_WINDOW = 30


def load_bars_from_csv(path: Path) -> list[BarData]:
    bars: list[BarData] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row["datetime"][:10], "%Y-%m-%d")
            bars.append(
                BarData(
                    gateway_name=GATEWAY,
                    symbol=SYMBOL,
                    exchange=EXCHANGE,
                    datetime=dt,
                    interval=Interval.DAILY,
                    volume=float(row.get("volume") or 0),
                    open_interest=float(row.get("open_interest") or 0),
                    open_price=float(row["open"]),
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    close_price=float(row["close"]),
                )
            )
    bars.sort(key=lambda b: b.datetime)
    return bars


def main() -> None:
    bars = load_bars_from_csv(CSV_PATH)
    if not bars:
        raise SystemExit(f"No bars loaded from {CSV_PATH}")

    start = bars[0].datetime
    end = bars[-1].datetime

    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=VT_SYMBOL,
        interval=Interval.DAILY,
        start=start,
        end=end,
        rate=0.0001,
        slippage=1,
        size=10,
        pricetick=1,
        capital=1_000_000,
    )
    engine.add_strategy(
        DoubleMaStrategy,
        {"fast_window": FAST_WINDOW, "slow_window": SLOW_WINDOW},
    )

    # Feed CSV bars directly (skip database load_data)
    engine.history_data = bars
    engine.output(f"Loaded {len(bars)} daily bars from CSV: {start.date()} -> {end.date()}")

    engine.run_backtesting()
    df = engine.calculate_result()
    stats = engine.calculate_statistics()

    lines = [
        "Double-MA CTA backtest (RB continuous daily via AKShare)",
        f"CSV: {CSV_PATH}",
        f"vt_symbol: {VT_SYMBOL}",
        f"interval: DAILY",
        f"date_range: {start.date()} -> {end.date()}",
        f"bars: {len(bars)}",
        f"strategy: DoubleMaStrategy fast={FAST_WINDOW} slow={SLOW_WINDOW}",
        f"size=10 pricetick=1 rate=0.0001 slippage=1 capital=1000000",
        "",
        "=== Statistics ===",
    ]
    for k, v in stats.items():
        lines.append(f"{k}: {v}")

    STATS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    if df is not None and not df.empty:
        out = df.copy()
        if "balance" in out.columns:
            out[["net_pnl", "balance"]].to_csv(EQUITY_PATH, encoding="utf-8-sig")
        else:
            out.to_csv(EQUITY_PATH, encoding="utf-8-sig")
        print(f"\nEquity CSV: {EQUITY_PATH}")

    print(f"Stats file: {STATS_PATH}")


if __name__ == "__main__":
    main()
