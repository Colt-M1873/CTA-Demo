# -*- coding: utf-8 -*-
"""Download 8 more commodity futures dailies to reach a 20-commodity pool."""
from __future__ import annotations

from pathlib import Path
import time

import akshare as ak
import pandas as pd

OUT_DIR = Path(r"C:\Users\Administrator\Desktop\vnpy\data")
SUMMARY_PATH = OUT_DIR / "download_commodity_expand20_summary.txt"

# Already present commodities (do not re-download for pool count)
EXISTING = {"AG", "AU", "CF", "CU", "I", "M", "MA", "RB", "RU", "SC", "TA", "Y"}

# Priority order until 8 succeed
CANDIDATES = [
    ("J", "J0", "焦炭"),
    ("JM", "JM0", "焦煤"),
    ("P", "P0", "棕榈油"),
    ("L", "L0", "塑料"),
    ("PP", "PP0", "聚丙烯"),
    ("V", "V0", "PVC"),
    ("FG", "FG0", "玻璃"),
    ("SA", "SA0", "纯碱"),
    ("HC", "HC0", "热卷"),
    ("AL", "AL0", "铝"),
    ("ZN", "ZN0", "锌"),
    ("NI", "NI0", "镍"),
    ("BU", "BU0", "沥青"),
    ("EB", "EB0", "苯乙烯"),
    ("SN", "SN0", "锡"),
    ("PB", "PB0", "铅"),
    ("A", "A0", "豆一"),
    ("C", "C0", "玉米"),
    ("RM", "RM0", "菜粕"),
    ("OI", "OI0", "菜油"),
    ("SR", "SR0", "白糖"),
]

ALTERNATES: dict[str, list[str]] = {
    "J": ["J0", "j0"],
    "JM": ["JM0", "jm0"],
    "P": ["P0", "p0"],
    "L": ["L0", "l0"],
    "PP": ["PP0", "pp0"],
    "V": ["V0", "v0"],
    "FG": ["FG0", "fg0"],
    "SA": ["SA0", "sa0"],
    "HC": ["HC0", "hc0"],
    "AL": ["AL0", "al0"],
    "ZN": ["ZN0", "zn0"],
    "NI": ["NI0", "ni0"],
    "BU": ["BU0", "bu0"],
    "EB": ["EB0", "eb0"],
    "SN": ["SN0", "sn0"],
    "PB": ["PB0", "pb0"],
    "A": ["A0", "a0"],
    "C": ["C0", "c0"],
    "RM": ["RM0", "rm0"],
    "OI": ["OI0", "oi0"],
    "SR": ["SR0", "sr0"],
}

TARGET_NEW = 8
RETRIES = 2
RETRY_SLEEP = 2.0


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
    for attempt in range(1, RETRIES + 1):
        for sym in sina_symbols:
            try:
                raw = ak.futures_zh_daily_sina(symbol=sym)
                if raw is None or len(raw) == 0:
                    raise ValueError(f"empty dataframe for {sym}")
                return sym, normalize(raw)
            except Exception as exc:
                last_err = exc
                print(f"  failed {sym} (attempt {attempt}): {type(exc).__name__}: {exc}")
        if attempt < RETRIES:
            time.sleep(RETRY_SLEEP)
    raise RuntimeError(f"all symbols failed; last={last_err}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"akshare version: {ak.__version__}")
    print(f"existing commodities: {sorted(EXISTING)}")
    print()

    successes: list[str] = []
    failures: list[str] = []
    skipped: list[str] = []
    new_codes: list[tuple[str, str]] = []

    for file_code, primary, name_cn in CANDIDATES:
        if len(new_codes) >= TARGET_NEW:
            break
        path = OUT_DIR / f"{file_code}_daily_main_sina.csv"
        if file_code in EXISTING or path.exists():
            line = f"SKIP\t{file_code}\t{primary}\t{name_cn}\talready exists"
            print(f"[{file_code}] {name_cn} -> {line}")
            skipped.append(line)
            continue

        alts = ALTERNATES.get(file_code, [primary])
        symbols: list[str] = []
        for s in [primary] + alts:
            if s not in symbols:
                symbols.append(s)

        print(f"[{file_code}] {name_cn} trying {symbols} ...")
        try:
            used, df = try_download(symbols)
            df.to_csv(path, index=False, encoding="utf-8")
            start = df["datetime"].min()
            end = df["datetime"].max()
            rows = len(df)
            line = (
                f"OK\t{file_code}\t{used}\t{name_cn}\trows={rows}\t"
                f"start={start.date()}\tend={end.date()}\tpath={path}"
            )
            print(f"  -> {line}")
            successes.append(line)
            new_codes.append((file_code, name_cn))
        except Exception as exc:
            line = f"FAIL\t{file_code}\t{primary}\t{name_cn}\t{type(exc).__name__}: {exc}"
            print(f"  -> {line}")
            failures.append(line)
        print()

    commodity_names = {
        "AG": "白银", "AU": "黄金", "CF": "棉花", "CU": "铜",
        "I": "铁矿石", "M": "豆粕", "MA": "甲醇", "RB": "螺纹钢",
        "RU": "橡胶", "SC": "原油", "TA": "PTA", "Y": "豆油",
        "J": "焦炭", "JM": "焦煤", "P": "棕榈油", "L": "塑料",
        "PP": "聚丙烯", "V": "PVC", "FG": "玻璃", "SA": "纯碱",
        "HC": "热卷", "AL": "铝", "ZN": "锌", "NI": "镍",
        "BU": "沥青", "EB": "苯乙烯", "SN": "锡", "PB": "铅",
        "A": "豆一", "C": "玉米", "RM": "菜粕", "OI": "菜油", "SR": "白糖",
    }
    financials = {"IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"}
    all_csvs = sorted(p.stem.replace("_daily_main_sina", "") for p in OUT_DIR.glob("*_daily_main_sina.csv"))
    commodities = [c for c in all_csvs if c not in financials]

    with SUMMARY_PATH.open("w", encoding="utf-8") as f:
        f.write(f"akshare_version={ak.__version__}\n")
        f.write("api=ak.futures_zh_daily_sina\n")
        f.write(f"out_dir={OUT_DIR}\n")
        f.write(f"target_new={TARGET_NEW}\n\n")
        f.write("=== SUCCESS (new) ===\n")
        for line in successes:
            f.write(line + "\n")
        f.write("\n=== SKIP ===\n")
        for line in skipped:
            f.write(line + "\n")
        f.write("\n=== FAIL ===\n")
        if failures:
            for line in failures:
                f.write(line + "\n")
        else:
            f.write("(none)\n")
        f.write(f"\n=== COMMODITY POOL ({len(commodities)}) ===\n")
        for c in commodities:
            f.write(f"{c}\t{commodity_names.get(c, '?')}\n")

    print("=== SUMMARY ===")
    print(f"new_success={len(successes)} fail={len(failures)} skip={len(skipped)}")
    print(f"commodity_count={len(commodities)}")
    print("commodities:")
    for c in commodities:
        print(f"  {c}\t{commodity_names.get(c, '?')}")
    print(f"wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
