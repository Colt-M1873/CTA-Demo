# -*- coding: utf-8 -*-
"""Trend-gated XS multifactor with fake-breakout filter + equal-weight sizing.

NO XGBoost. Builds on equal-weight factor scoring; changes vs baseline ATR version:
1) Entry requires Donchian gate PLUS fake-breakout confirmation (body + volume).
2) Position sizing is equal capital weight across selected names (not ATR lots).

Exit still uses raw Donchian gate (filter only blocks new entries).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

# Reuse the same 20-commodity universe specs as the ATR baseline
COMMODITY_SPECS: dict[str, dict] = {
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

ENTRY_WINDOW = 20
ATR_WINDOW = 20
MOM_WINDOWS = (20, 60, 120)
OI_WINDOW = 20
VOL_WINDOW = 20
VOL_SMA_WINDOW = 20
SELECT_PCT = 0.25
MIN_POOL_FOR_PCT = 4
REBALANCE_EVERY_N_DAYS = 5
CAPITAL = 1_000_000.0
COMMISSION_RATE = 0.0001
MIN_HISTORY = 130

# Fake-breakout filter
BODY_ATR_MIN = 0.25  # |close-open|/ATR must be >= this and signed with trade direction
# Equal-weight sizing
GROSS_LEVERAGE = 1.0  # sum of absolute capital weights across selected names
MAX_LOTS_PER_NAME = 50


@dataclass
class Position:
    symbol: str
    direction: int
    lots: int
    entry_price: float
    entry_date: pd.Timestamp


def robust_zscore(series: pd.Series) -> pd.Series:
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
    """Gate, ATR, factors, and fake-breakout filter flags. Leak-free where noted."""
    out = df.copy()
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
    out["low_vol"] = -out["vol_20"]

    oi = out["open_interest"].astype(float)
    out["oi_chg_20"] = oi.pct_change(OI_WINDOW).replace([np.inf, -np.inf], np.nan)

    # --- Fake-breakout filter components (EOD; trade at close) ---
    atr = out["atr"]
    body = out["close"] - out["open"]
    out["body_atr"] = body / atr.replace(0, np.nan)
    # Prior 20d average volume (exclude today) — leak-free vs using today's bar in the avg
    out["vol_sma_20_prior"] = (
        out["volume"].astype(float).rolling(VOL_SMA_WINDOW, min_periods=VOL_SMA_WINDOW).mean().shift(1)
    )
    out["vol_confirm"] = out["volume"].astype(float) > out["vol_sma_20_prior"]

    # Body confirms direction relative to BODY_ATR_MIN
    out["body_long_ok"] = out["body_atr"] >= BODY_ATR_MIN
    out["body_short_ok"] = out["body_atr"] <= -BODY_ATR_MIN

    # Entry eligibility = Donchian gate AND body confirm AND volume confirm
    out["long_enter_ok"] = (
        out["long_eligible"].fillna(False)
        & out["body_long_ok"].fillna(False)
        & out["vol_confirm"].fillna(False)
    )
    out["short_enter_ok"] = (
        out["short_eligible"].fillna(False)
        & out["body_short_ok"].fillna(False)
        & out["vol_confirm"].fillna(False)
    )

    return out


def composite_scores(pool: pd.DataFrame, factor_cols: Iterable[str]) -> pd.Series:
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


def equal_weight_lots(
    capital: float,
    price: float,
    size: float,
    n_names: int,
    gross_leverage: float = GROSS_LEVERAGE,
    max_lots: int = MAX_LOTS_PER_NAME,
) -> int:
    """Equal capital weight per selected name.

    weight = gross_leverage / n_names
    lots = floor(capital * weight / (price * multiplier))
    If lots < 1 (cannot afford one contract), return 0.
    Cap at max_lots.
    """
    if (
        not np.isfinite(price)
        or not np.isfinite(size)
        or price <= 0
        or size <= 0
        or n_names <= 0
        or capital <= 0
    ):
        return 0
    weight = float(gross_leverage) / float(n_names)
    budget = capital * weight
    contract_value = price * size
    if contract_value <= 0:
        return 0
    lots = int(np.floor(budget / contract_value))
    if lots < 1:
        return 0
    return int(min(lots, max_lots))


FACTOR_COLS = ["mom_20", "mom_60", "mom_120", "low_vol", "oi_chg_20"]
