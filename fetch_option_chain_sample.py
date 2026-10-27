# -*- coding: utf-8 -*-
"""复现：用 AKShare 1.19.3 拉取沪深300 / 商品期权链样例。

输出目录: C:\\Users\\Administrator\\Desktop\\vnpy\\data\\options_sample\\
仅包含本次验证成功的调用。
"""
from __future__ import annotations

from pathlib import Path

import akshare as ak
import pandas as pd

OUT = Path(r"C:\Users\Administrator\Desktop\vnpy\data\options_sample")
OUT.mkdir(parents=True, exist_ok=True)


def save(name: str, df: pd.DataFrame) -> Path:
    path = OUT / f"{name}.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"OK {name}: rows={len(df)} cols={list(df.columns)} -> {path}")
    return path


def main() -> None:
    print("akshare", ak.__version__)

    # ---- 1) 沪深300股指期权（中金所 / 新浪）----
    listing = ak.option_cffex_hs300_list_sina()
    months = listing.get("沪深300指数") or next(iter(listing.values()))
    print("HS300 months:", months)
    near = months[0]

    spot = ak.option_cffex_hs300_spot_sina(symbol=near)
    save(f"option_cffex_hs300_spot_sina_symbol-{near}", spot)

    for end_month in ("2511", "2512", "2601"):
        board = ak.option_finance_board(symbol="沪深300股指期权", end_month=end_month)
        if board is not None and not board.empty:
            save(f"option_finance_board_hs300_index_{end_month}", board)

    for end_month in ("2511", "2512", "2603"):
        try:
            etf = ak.option_finance_board(symbol="华泰柏瑞沪深300ETF期权", end_month=end_month)
            if etf is not None and not etf.empty:
                save(f"option_finance_board_510300_{end_month}", etf)
        except Exception as e:
            print(f"SKIP ETF board {end_month}: {e}")

    call_id_col = [c for c in spot.columns if "标识" in str(c) and "看涨" in str(c)]
    if call_id_col:
        code = str(spot[call_id_col[0]].dropna().iloc[0])
        daily = ak.option_cffex_hs300_daily_sina(symbol=code)
        save(f"option_cffex_hs300_daily_sina_symbol-{code}", daily)

    sse_months = ak.option_sse_list_sina(symbol="300ETF", exchange="null")
    save("option_sse_list_sina_300ETF", pd.DataFrame({"month": sse_months}))
    expire = next((m for m in ("202611", "202612", "202610", "202703") if m in sse_months), sse_months[0])
    codes = ak.option_sse_codes_sina(symbol="看涨期权", trade_date=expire, underlying="510300")
    save(f"option_sse_codes_sina_call_{expire}_510300", codes)
    code_col = [c for c in codes.columns if "代码" in str(c)][0]
    opt_code = str(codes[code_col].iloc[0])
    greeks = ak.option_sse_greeks_sina(symbol=opt_code)
    save(f"option_sse_greeks_sina_{opt_code}", greeks)
    px = ak.option_sse_spot_price_sina(symbol=opt_code)
    save(f"option_sse_spot_price_sina_{opt_code}", px)

    # ---- 2) 商品期货期权 ----
    for sym, n_keep in (("黄金期权", 2), ("沪铜期权", 1), ("螺纹钢期权", 1)):
        contracts = ak.option_commodity_contract_sina(symbol=sym)
        save(f"option_commodity_contract_sina_{sym}", contracts)
        col = "合约" if "合约" in contracts.columns else contracts.columns[1]
        for contract in contracts[col].astype(str).head(n_keep):
            table = ak.option_commodity_contract_table_sina(symbol=sym, contract=contract)
            save(f"option_commodity_contract_table_sina_{sym}_{contract}", table)
            id_cols = [c for c in table.columns if "期权合约" in str(c) and "看涨" in str(c)]
            if id_cols:
                oc = str(table[id_cols[0]].dropna().iloc[0])
                hist = ak.option_commodity_hist_sina(symbol=oc)
                save(f"option_commodity_hist_sina_{oc}", hist)

    trade_date = "20261027"
    for sym in ("黄金期权", "铜期权"):
        hist = ak.option_hist_shfe(symbol=sym, trade_date=trade_date)
        if hist is not None and not hist.empty:
            save(f"option_hist_shfe_{sym}_{trade_date}", hist)
        vol = ak.option_vol_shfe(symbol=sym, trade_date=trade_date)
        if vol is not None and not vol.empty:
            save(f"option_vol_shfe_{sym}_{trade_date}", vol)

    print("done ->", OUT)


if __name__ == "__main__":
    main()
