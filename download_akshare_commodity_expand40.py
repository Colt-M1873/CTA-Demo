# -*- coding: utf-8 -*-
"""Download ~20 more commodity futures dailies to reach a ~40-commodity pool."""
from __future__ import annotations

from pathlib import Path
import time

import akshare as ak
import pandas as pd

OUT_DIR = Path(r"C:\Users\Administrator\Desktop\vnpy\data")
SUMMARY_PATH = OUT_DIR / "download_commodity_expand40_summary.txt"

# Already present commodities (do not re-download for pool count)
EXISTING = {
    "AG", "AU", "CF", "CU", "FG", "I", "J", "JM", "L", "M",
    "MA", "P", "PP", "RB", "RU", "SA", "SC", "TA", "V", "Y",
}

# Priority order until ~20 succeed (liquid metals / energy / ag / chemicals)
CANDIDATES = [
    ("HC", "HC0", "热卷"),
    ("AL", "AL0", "铝"),
    ("ZN", "ZN0", "锌"),
    ("NI", "NI0", "镍"),
    ("SN", "SN0", "锡"),
    ("PB", "PB0", "铅"),
    ("BU", "BU0", "沥青"),
    ("EB", "EB0", "苯乙烯"),
    ("EG", "EG0", "乙二醇"),
    ("SP", "SP0", "纸浆"),
    ("FU", "FU0", "燃油"),
    ("UR", "UR0", "尿素"),
    ("RM", "RM0", "菜粕"),
    ("OI", "OI0", "菜油"),
    ("SR", "SR0", "白糖"),
    ("A", "A0", "豆一"),
    ("C", "C0", "玉米"),
    ("CS", "CS0", "玉米淀粉"),
    ("B", "B0", "豆二"),
    ("JD", "JD0", "鸡蛋"),
    ("LH", "LH0", "生猪"),
    ("SI", "SI0", "工业硅"),
    ("LC", "LC0", "碳酸锂"),
    ("PX", "PX0", "对二甲苯"),
    ("SH", "SH0", "烧碱"),
    ("PF", "PF0", "短纤"),
    ("CY", "CY0", "棉纱"),
    ("AP", "AP0", "苹果"),
    ("CJ", "CJ0", "红枣"),
    ("PK", "PK0", "花生"),
    ("SM", "SM0", "锰硅"),
    ("SF", "SF0", "硅铁"),
    ("ZC", "ZC0", "动力煤"),
]

ALTERNATES: dict[str, list[str]] = {
    "HC": ["HC0", "hc0"],
    "AL": ["AL0", "al0"],
    "ZN": ["ZN0", "zn0"],
    "NI": ["NI0", "ni0"],
    "SN": ["SN0", "sn0"],
    "PB": ["PB0", "pb0"],
    "BU": ["BU0", "bu0"],
    "EB": ["EB0", "eb0"],
    "EG": ["EG0", "eg0"],
    "SP": ["SP0", "sp0"],
    "FU": ["FU0", "fu0"],
    "UR": ["UR0", "ur0"],
    "RM": ["RM0", "rm0"],
    "OI": ["OI0", "oi0"],
    "SR": ["SR0", "sr0"],
    "A": ["A0", "a0"],
    "C": ["C0", "c0"],
    "CS": ["CS0", "cs0"],
    "B": ["B0", "b0"],
    "JD": ["JD0", "jd0"],
    "LH": ["LH0", "lh0"],
    "SI": ["SI0", "si0"],
    "LC": ["LC0", "lc0"],
    "PX": ["PX0", "px0"],
    "SH": ["SH0", "sh0"],
    "PF": ["PF0", "pf0"],
    "CY": ["CY0", "cy0"],
    "AP": ["AP0", "ap0"],
    "CJ": ["CJ0", "cj0"],
    "PK": ["PK0", "pk0"],
    "SM": ["SM0", "sm0"],
    "SF": ["SF0", "sf0"],
    "ZC": ["ZC0", "zc0", "ZM0", "zm0"],
}

TARGET_NEW = 20
RETRIES = 2
RETRY_SLEEP = 2.0

COMMODITY_NAMES = {
    "AG": "白银", "AU": "黄金", "CF": "棉花", "CU": "铜",
    "FG": "玻璃", "I": "铁矿石", "J": "焦炭", "JM": "焦煤",
    "L": "塑料", "M": "豆粕", "MA": "甲醇", "P": "棕榈油",
    "PP": "聚丙烯", "RB": "螺纹钢", "RU": "橡胶", "SA": "纯碱",
    "SC": "原油", "TA": "PTA", "V": "PVC", "Y": "豆油",
    "HC": "热卷", "AL": "铝", "ZN": "锌", "NI": "镍",
    "SN": "锡", "PB": "铅", "BU": "沥青", "EB": "苯乙烯",
    "EG": "乙二醇", "SP": "纸浆", "FU": "燃油", "UR": "尿素",
    "RM": "菜粕", "OI": "菜油", "SR": "白糖", "A": "豆一",
    "C": "玉米", "CS": "玉米淀粉", "B": "豆二", "JD": "鸡蛋",
    "LH": "生猪", "SI": "工业硅", "LC": "碳酸锂", "PX": "对二甲苯",
    "SH": "烧碱", "PF": "短纤", "CY": "棉纱", "AP": "苹果",
    "CJ": "红枣", "PK": "花生", "SM": "锰硅", "SF": "硅铁",
    "ZC": "动力煤",
}

FINANCIALS = {"IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"}


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
    print(f"target_new={TARGET_NEW}")
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

    all_csvs = sorted(
        p.stem.replace("_daily_main_sina", "")
        for p in OUT_DIR.glob("*_daily_main_sina.csv")
    )
    commodities = [c for c in all_csvs if c not in FINANCIALS]

    pool_lines: list[str] = []
    for c in commodities:
        path = OUT_DIR / f"{c}_daily_main_sina.csv"
        try:
            df = pd.read_csv(path, parse_dates=["datetime"])
            rows = len(df)
            start = df["datetime"].min().date()
            end = df["datetime"].max().date()
            pool_lines.append(
                f"{c}\t{COMMODITY_NAMES.get(c, '?')}\trows={rows}\t"
                f"start={start}\tend={end}"
            )
        except Exception as exc:
            pool_lines.append(
                f"{c}\t{COMMODITY_NAMES.get(c, '?')}\tERROR={type(exc).__name__}: {exc}"
            )

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
        if not skipped:
            f.write("(none)\n")
        f.write("\n=== FAIL ===\n")
        if failures:
            for line in failures:
                f.write(line + "\n")
        else:
            f.write("(none)\n")
        f.write(f"\n=== COMMODITY POOL ({len(commodities)}) ===\n")
        for line in pool_lines:
            f.write(line + "\n")

    print("=== SUMMARY ===")
    print(f"new_success={len(successes)} fail={len(failures)} skip={len(skipped)}")
    print(f"commodity_count={len(commodities)}")
    print("commodities:")
    for line in pool_lines:
        print(f"  {line}")
    print(f"wrote {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
