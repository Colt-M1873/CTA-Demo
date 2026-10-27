# -*- coding: utf-8 -*-
"""Trend-gated cross-sectional multifactor logic (commodity futures).

Pure functions + helpers used by backtest_trend_xs_multifactor.py.
No look-ahead: Donchian gate uses prior-bar highs/lows; factors use closes
through the signal bar (trade assumed at that bar's close for daily data).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

# Commodity universe (exclude CFFEX financials IF/IH/IC/IM/T/TF/TS/TL)
COMMODITY_SPECS: dict[str, dict] = {
    # 20-commodity equal-weight XS universe (no CFFEX financials)
    "AG": {"csv": "AG_daily_main_sina.csv", "size": 15, "pricetick": 1.0, "exchange": "SHFE"},
    "AU": {"csv": "AU_daily_main_sina.csv", "size": 1000, "pricetick": 0.02, "exchange": "SHFE"},
    "CF": {"csv": "CF_daily_main_sina.csv", "size": 5, "pricetick": 5.0, "exchange": "CZCE"},
    "CU": {"csv": "CU_daily_main_sina.csv", "size": 5, "pricetick": 10.0, "exchange": "SHFE"},
    "FG": {"csv": "FG_daily_main_sina.csv", "size": 20, "pricetick": 1.0, "exchange": "CZCE"},
    "I": {"csv": "I_daily_main_sina.csv", "size": 100, "pricetick": 0.5, "exchange": "DCE"},
    "J": {"csv": "J_daily_main_sina.csv", "size": 100, "pricetick": 0.5, "exchange": "DCE"},
    "JM": {"csv": "JM_daily_main_sina.csv", "size": 60, "pricetick": 0.5, "exchange": "DCE"},
    "L": {"csv": "L_daily_main_sina.csv", "size": 5, "pricetick": 5.0, "exchange": "DCE"},
    "M": {"csv": "M_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "MA": {"csv": "MA_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "CZCE"},
    "P": {"csv": "P_daily_main_sina.csv", "size": 10, "pricetick": 2.0, "exchange": "DCE"},
    "PP": {"csv": "PP_daily_main_sina.csv", "size": 5, "pricetick": 1.0, "exchange": "DCE"},
    "RB": {"csv": "RB_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "SHFE"},
    "RU": {"csv": "RU_daily_main_sina.csv", "size": 10, "pricetick": 5.0, "exchange": "SHFE"},
    "SA": {"csv": "SA_daily_main_sina.csv", "size": 20, "pricetick": 1.0, "exchange": "CZCE"},
    "SC": {"csv": "SC_daily_main_sina.csv", "size": 1000, "pricetick": 0.1, "exchange": "INE"},
    "TA": {"csv": "TA_daily_main_sina.csv", "size": 5, "pricetick": 2.0, "exchange": "CZCE"},
    "V": {"csv": "V_daily_main_sina.csv", "size": 5, "pricetick": 5.0, "exchange": "DCE"},
    "Y": {"csv": "Y_daily_main_sina.csv", "size": 10, "pricetick": 2.0, "exchange": "DCE"},
}

FINANCIAL_EXCLUDE = {"IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"}

ENTRY_WINDOW = 20
ATR_WINDOW = 20
MOM_WINDOWS = (20, 60, 120)
OI_WINDOW = 20
VOL_WINDOW = 20
SELECT_PCT = 0.25  # middle of 20–30%
MIN_POOL_FOR_PCT = 4
REBALANCE_EVERY_N_DAYS = 5  # every 5 trading days on master calendar
CAPITAL = 1_000_000.0
COMMISSION_RATE = 0.0001
# Dollar risk target per selected name ≈ this fraction of capital per ATR-day
RISK_FRAC_PER_NAME = 0.01
MAX_LOTS_PER_NAME = 20
MIN_HISTORY = 130  # need ~120d momentum + buffer


@dataclass
class Position:
    symbol: str
    direction: int  # +1 long, -1 short
    lots: int
    entry_price: float
    entry_date: pd.Timestamp


def robust_zscore(series: pd.Series) -> pd.Series:
    """Median / MAD robust scale. Returns 0 if MAD~0."""
    x = series.astype(float)
    med = x.median()
    mad = (x - med).abs().median()
    if mad is None or not np.isfinite(mad) or mad < 1e-12:
        return pd.Series(0.0, index=x.index)
    return (x - med) / mad


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev).abs(),
            (low - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add gate flags, ATR, and raw factors. Index must be datetime ascending."""
    out = df.copy()
    # Prior-bar Donchian (no same-bar high/low in channel)
    prior_high = out["high"].rolling(ENTRY_WINDOW, min_periods=ENTRY_WINDOW).max().shift(1)
    prior_low = out["low"].rolling(ENTRY_WINDOW, min_periods=ENTRY_WINDOW).min().shift(1)
    out["donchian_high"] = prior_high
    out["donchian_low"] = prior_low
    out["long_eligible"] = out["close"] > prior_high
    out["short_eligible"] = out["close"] < prior_low

    out["atr"] = true_range(out["high"], out["low"], out["close"]).rolling(
        ATR_WINDOW, min_periods=ATR_WINDOW
    ).mean()

    for w in MOM_WINDOWS:
        out[f"mom_{w}"] = out["close"].pct_change(w)

    out["ret_1"] = out["close"].pct_change(1)
    out["vol_20"] = out["ret_1"].rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()
    out["low_vol"] = -out["vol_20"]  # higher score = lower vol

    oi = out["open_interest"].astype(float)
    out["oi_chg_20"] = oi.pct_change(OI_WINDOW).replace([np.inf, -np.inf], np.nan)

    return out


def composite_scores(pool: pd.DataFrame, factor_cols: Iterable[str]) -> pd.Series:
    """Equal-weight sum of robust-z factors over symbols in pool (rows = symbols)."""
    parts = []
    for col in factor_cols:
        if col not in pool.columns:
            continue
        s = pool[col].dropna()
        if len(s) < 2:
            continue
        z = robust_zscore(s)
        parts.append(z.reindex(pool.index))
    if not parts:
        return pd.Series(0.0, index=pool.index)
    mat = pd.concat(parts, axis=1)
    return mat.mean(axis=1, skipna=True)


def select_names(scores: pd.Series, side: str, pct: float = SELECT_PCT) -> list[str]:
    """side='long' -> top pct; side='short' -> bottom pct."""
    s = scores.dropna().sort_values(ascending=False)
    n = len(s)
    if n == 0:
        return []
    if n < MIN_POOL_FOR_PCT:
        k = 1
    else:
        k = max(1, int(np.floor(n * pct)))
    if side == "long":
        return list(s.head(k).index)
    return list(s.tail(k).index)


def atr_lots(capital: float, atr: float, size: float, n_names: int,
             risk_frac: float = RISK_FRAC_PER_NAME,
             max_lots: int = MAX_LOTS_PER_NAME) -> int:
    """Equal-vol / ATR targeting across selected names.

    Dollar risk per name ≈ capital * risk_frac / max(n_names, 1)
    lots = floor( risk_dollars / (ATR * contract_size) )
    """
    if atr is None or not np.isfinite(atr) or atr <= 0 or size <= 0:
        return 0
    n = max(int(n_names), 1)
    risk_dollars = capital * risk_frac / n
    raw = risk_dollars / (atr * size)
    lots = int(np.floor(raw))
    if lots < 1 and raw >= 0.35:
        lots = 1  # allow tiny risk names to take 1 lot if close
    return int(min(max(lots, 0), max_lots))


FACTOR_COLS = ["mom_20", "mom_60", "mom_120", "low_vol", "oi_chg_20"]
