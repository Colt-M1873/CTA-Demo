# -*- coding: utf-8 -*-
"""Download multiple China futures daily histories via AKShare (sina continuous)."""
from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd

OUT_DIR = Path(r"C:\\Users\\Administrator\\Desktop\\vnpy\\data")
SUMMARY_PATH = OUT_DIR / "download_summary.txt"

# (file_code, sina_symbol, name_cn) — skip RB0 (already downloaded)
CANDIDATES = [
    ("AU", "AU0", "黄金"),
    ("AG", "AG0", "白银"),
    ("CU", "CU0", "铜"),
    ("I", "I0", "铁矿石"),
    ("M", "M0", "豆粕"),
    ("Y", "Y0", "豆油"),
    ("TA", "TA0", "PTA"),
    ("MA", "MA0", "甲醇"),
    ("CF", "CF0", "棉花"),
    ("IF", "IF0", "沪深300股指"),
    ("SC", "SC0", "原油"),
]

ALTERNATES: dict[str, list[str]] = {
    "TA": ["TA0", "PTA0"],
    "I": ["I0", "i0"],
    "SC": ["SC0", "sc0"],
    "IF": ["IF0", "if0"],
}


def normalize(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns={"date": "datetime", "hold": "open_interest"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)
    cols = ["datetime", "open", "high", "low", "close", "volume", "open_interest"]
    if "settle" in df.columns:
        cols.append("settle")
    return df[cols]


def try_download(sina_symbols: list[str]) -> tuple[str, pd.DataFrame]:
    last_err: Exception | None = None
    for sym in sina_symbols:
        try:
            raw = ak.futures_zh_daily_sina(symbol=sym)
            if raw is None or len(raw) == 0:
                raise ValueError(f"empty dataframe for {sym}")
            return sym, normalize(raw)
        except Exception as exc:
            last_err = exc
            print(f"  failed {sym}: {type(exc).__name__}: {exc}")
    raise RuntimeError(f"all symbols failed; last={last_err}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"akshare version: {ak.__version__}")
    print()

    successes: list[str] = []
    failures: list[str] = []

    for file_code, primary, name_cn in CANDIDATES:
        alts = ALTERNATES.get(file_code, [primary])
        symbols = []
        for s in [primary] + alts:
            if s not in symbols:
                symbols.append(s)

        print(f"[{file_code}] {name_cn} trying {symbols} ...")
        try:
            used, df = try_download(symbols)
            path = OUT_DIR / f"{file_code}_daily_main_sina.csv"
            df.to_csv(path, index=False, encoding="utf-8")
            start = df["datetime"].min()
            end = df["datetime"].max()
            rows = len(df)
            line = (
                f"OK\\t{file_code}\\t{used}\\t{name_cn}\\trows={rows}\\t"
                f"start={start.date()}\\tend={end.date()}\\tpath={path}"
            )
            print(f"  -> {line}")
            successes.append(line)
        except Exception as exc:
            line = f"FAIL\\t{file_code}\\t{primary}\\t{name_cn}\\t{type(exc).__name__}: {exc}"
            print(f"  -> {line}")
            failures.append(line)
        print()

    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        f.write(f"akshare_version={ak.__version__}\\n")
        f.write("api=ak.futures_zh_daily_sina\\n")
        f.write(f"out_dir={OUT_DIR}\\n")
        f.write("skipped=RB0 (already present as RB_daily_main_sina.csv)\\n\\n")
        f.write("=== SUCCESS ===\\n")
        for line in successes:
            f.write(line + "\\n")
        f.write("\\n=== FAIL ===\\n")
        if failures:
            for line in failures:
                f.write(line + "\\n")
        else:
            f.write("(none)\\n")

    print("=== SUMMARY ===")
    print(f"success={len(successes)} fail={len(failures)}")
    print(f"wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
