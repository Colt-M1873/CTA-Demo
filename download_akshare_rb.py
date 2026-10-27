# -*- coding: utf-8 -*-
"""Download RB (rebar) futures history via AKShare for vnpy learning."""
from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd

OUT_DIR = Path(r"C:\Users\Administrator\Desktop\vnpy\data")
SYMBOL = "RB0"  # sina continuous main for 螺纹钢


def save_daily() -> Path:
    """Long daily history of RB continuous main (sina)."""
    raw = ak.futures_zh_daily_sina(symbol=SYMBOL)
    # columns already: date, open, high, low, close, volume, hold, settle
    df = raw.rename(
        columns={
            "date": "datetime",
            "hold": "open_interest",
        }
    )
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    # keep settle as optional extra column
    cols = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
    if "settle" in df.columns:
        cols.append("settle")
    df = df[cols]

    path = OUT_DIR / "RB_daily_main_sina.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def save_minute_sample(period: str = "5") -> Path:
    """Shorter minute sample for continuous main (sina; recent bars only)."""
    raw = ak.futures_zh_minute_sina(symbol=SYMBOL, period=period)
    df = raw.rename(columns={"hold": "open_interest"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    df = df[["datetime", "open", "high", "low", "close", "volume", "open_interest"]]

    path = OUT_DIR / f"RB_minute{period}_main_sina_sample.csv"
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def report(path: Path) -> None:
    df = pd.read_csv(path, parse_dates=["datetime"])
    print(f"file: {path}")
    print(f"rows: {len(df)}")
    print(f"date_range: {df['datetime'].min()} .. {df['datetime'].max()}")
    print("sample (first 3):")
    print(df.head(3).to_string(index=False))
    print()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"akshare version: {ak.__version__}")
    print(f"symbol: {SYMBOL}")
    print()

    print("API: ak.futures_zh_daily_sina(symbol='RB0')")
    daily = save_daily()
    report(daily)

    print("API: ak.futures_zh_minute_sina(symbol='RB0', period='5')")
    try:
        minute = save_minute_sample("5")
        report(minute)
    except Exception as exc:
        print(f"minute sample failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
