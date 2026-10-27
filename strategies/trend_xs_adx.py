# -*- coding: utf-8 -*-
"""Trend-gated XS multifactor + fake-breakout filter + EW sizing + ADX factor.

NO XGBoost. Extends EW+filter rules with:
- ADX(14) Wilder as equal-weight cross-sectional scoring factor
- 40-commodity universe (all local *_daily_main_sina.csv commodities; no CFFEX financials)

Exit still uses raw Donchian gate (filter only blocks new entries).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

# 40-commodity universe (exclude CFFEX financials IF/IH/IC/IM/T/TF/TS/TL).
# size = contract multiplier (yuan per price point). Reasonable exchange defaults;
# used only for EW lot sizing / PnL scale — document if you refine ticks.
COMMODITY_SPECS: dict[str, dict] = {
    # --- original 20 ---
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
    # --- expand to 40 ---
    "A": {"csv": "A_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "AL": {"csv": "AL_daily_main_sina.csv", "size": 5, "pricetick": 5.0, "exchange": "SHFE"},
    "B": {"csv": "B_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "BU": {"csv": "BU_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "SHFE"},
    "C": {"csv": "C_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "CS": {"csv": "CS_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "EB": {"csv": "EB_daily_main_sina.csv", "size": 5, "pricetick": 1.0, "exchange": "DCE"},
    "EG": {"csv": "EG_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "FU": {"csv": "FU_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "SHFE"},
    "HC": {"csv": "HC_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "SHFE"},
    "JD": {"csv": "JD_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "DCE"},
    "NI": {"csv": "NI_daily_main_sina.csv", "size": 1, "pricetick": 10.0, "exchange": "SHFE"},
    "OI": {"csv": "OI_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "CZCE"},
    "PB": {"csv": "PB_daily_main_sina.csv", "size": 5, "pricetick": 5.0, "exchange": "SHFE"},
    "RM": {"csv": "RM_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "CZCE"},
    "SN": {"csv": "SN_daily_main_sina.csv", "size": 1, "pricetick": 10.0, "exchange": "SHFE"},
    "SP": {"csv": "SP_daily_main_sina.csv", "size": 10, "pricetick": 2.0, "exchange": "SHFE"},
    "SR": {"csv": "SR_daily_main_sina.csv", "size": 10, "pricetick": 1.0, "exchange": "CZCE"},
    "UR": {"csv": "UR_daily_main_sina.csv", "size": 20, "pricetick": 1.0, "exchange": "CZCE"},
    "ZN": {"csv": "ZN_daily_main_sina.csv", "size": 5, "pricetick": 5.0, "exchange": "SHFE"},
}

FINANCIAL_EXCLUDE = {"IF", "IH", "IC", "IM", "T", "TF", "TS", "TL"}

ENTRY_WINDOW = 20
ATR_WINDOW = 20
ADX_WINDOW = 14
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

BODY_ATR_MIN = 0.25
USE_VOLUME_FILTER = True
GROSS_LEVERAGE = 1.0
MAX_LOTS_PER_NAME = 50

# Directional factors: high = bullish. Non-directional strength/quality stay positive on both sides.
DIRECTIONAL_FACTORS = {"mom_20", "mom_60", "mom_120", "oi_chg_20"}
# ADX and low_vol: higher = preferred for both long and short ranking

DEFAULT_FACTOR_COLS = ["mom_20", "mom_60", "mom_120", "low_vol", "oi_chg_20", "adx"]
FACTOR_COLS = list(DEFAULT_FACTOR_COLS)

SIGNAL_PROFILES = {
    "baseline": {
        "entry_window": 20,
        "select_pct": 0.25,
        "rebalance_every_n_days": 5,
        "body_atr_min": 0.25,
        "use_volume_filter": True,
        "factor_cols": list(DEFAULT_FACTOR_COLS),
    },
    "signal_best": {
        "entry_window": 40,
        "select_pct": 0.25,
        "rebalance_every_n_days": 10,
        "body_atr_min": 0.25,
        "use_volume_filter": True,
        "factor_cols": ['mom_20', 'mom_60', 'mom_120', 'low_vol', 'oi_chg_20', 'adx'],
    },
}
_ACTIVE_SIGNAL_PROFILE = "baseline"


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


def wilder_rma(series: pd.Series, period: int) -> pd.Series:
    """Wilder RMA: first value = SMA of first `period` finite observations, then
    rma_t = (rma_{t-1}*(period-1) + x_t) / period.
    Contiguous daily bars assumed after leading NaNs.
    """
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    if n == 0 or period <= 0:
        return pd.Series(out, index=series.index)

    # skip leading NaNs
    i = 0
    while i < n and not np.isfinite(arr[i]):
        i += 1
    if i + period > n:
        return pd.Series(out, index=series.index)

    window = arr[i : i + period]
    if not np.all(np.isfinite(window)):
        # fall back: find first contiguous finite run of length period
        run = 0
        start = None
        for j in range(n):
            if np.isfinite(arr[j]):
                if run == 0:
                    start = j
                run += 1
                if run == period:
                    i = start
                    window = arr[i : i + period]
                    break
            else:
                run = 0
                start = None
        else:
            return pd.Series(out, index=series.index)

    end = i + period - 1
    out[end] = float(np.mean(window))
    for k in range(end + 1, n):
        if not np.isfinite(arr[k]) or not np.isfinite(out[k - 1]):
            out[k] = np.nan
            continue
        out[k] = (out[k - 1] * (period - 1) + arr[k]) / period
    return pd.Series(out, index=series.index)


def adx_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = ADX_WINDOW) -> pd.Series:
    """Standard Wilder ADX(period). Value at bar t uses OHLC through t (EOD-known).

    Leak-free under close-fill assumption: score/rebalance at bar close may use ADX_t.
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
        dtype=float,
    )
    # First bar has no prior high/low → DM/TR NaN
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan
    tr = true_range(high, low, close)

    atr = wilder_rma(tr, period)
    plus_dm_s = wilder_rma(plus_dm, period)
    minus_dm_s = wilder_rma(minus_dm, period)

    plus_di = 100.0 * plus_dm_s / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_s / atr.replace(0, np.nan)
    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
    adx = wilder_rma(dx, period)
    return adx


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Gate, ATR, ADX, factors, and fake-breakout filter flags."""
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

    # ADX(14) Wilder — known as of this bar's close
    out["adx"] = adx_wilder(out["high"], out["low"], out["close"], ADX_WINDOW)

    for w in MOM_WINDOWS:
        out[f"mom_{w}"] = out["close"].pct_change(w)

    out["ret_1"] = out["close"].pct_change(1)
    out["vol_20"] = out["ret_1"].rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()
    out["low_vol"] = -out["vol_20"]

    oi = out["open_interest"].astype(float)
    out["oi_chg_20"] = oi.pct_change(OI_WINDOW).replace([np.inf, -np.inf], np.nan)

    atr = out["atr"]
    body = out["close"] - out["open"]
    out["body_atr"] = body / atr.replace(0, np.nan)
    out["vol_sma_20_prior"] = (
        out["volume"].astype(float).rolling(VOL_SMA_WINDOW, min_periods=VOL_SMA_WINDOW).mean().shift(1)
    )
    out["vol_confirm"] = out["volume"].astype(float) > out["vol_sma_20_prior"]
    out["body_long_ok"] = out["body_atr"] >= BODY_ATR_MIN
    out["body_short_ok"] = out["body_atr"] <= -BODY_ATR_MIN
    long_ok = out["long_eligible"].fillna(False) & out["body_long_ok"].fillna(False)
    short_ok = out["short_eligible"].fillna(False) & out["body_short_ok"].fillna(False)
    if USE_VOLUME_FILTER:
        long_ok = long_ok & out["vol_confirm"].fillna(False)
        short_ok = short_ok & out["vol_confirm"].fillna(False)
    out["long_enter_ok"] = long_ok
    out["short_enter_ok"] = short_ok
    return out


def composite_scores(
    pool: pd.DataFrame,
    factor_cols: Iterable[str],
    side: str = "long",
) -> pd.Series:
    """Equal-weight robust-z composite.

    Directional factors (mom_*, oi_chg): high = bullish.
    For side='short', those z-scores are negated so higher composite = better short.
    Non-directional (adx, low_vol): always positive — higher ADX / lower vol preferred
    on both sides (strong trend for shorts, not weak chop).
    Selection should take the TOP of this score for both sides.
    """
    parts = []
    for col in factor_cols:
        if col not in pool.columns:
            continue
        s = pool[col].dropna()
        if len(s) < 2:
            continue
        z = robust_zscore(s)
        if side == "short" and col in DIRECTIONAL_FACTORS:
            z = -z
        parts.append(z.reindex(pool.index))
    if not parts:
        return pd.Series(0.0, index=pool.index)
    mat = pd.concat(parts, axis=1)
    return mat.mean(axis=1, skipna=True)


def select_names(scores: pd.Series, side: str, pct: float = SELECT_PCT) -> list[str]:
    """Always take top pct of scores (caller must side-adjust composite for shorts)."""
    s = scores.dropna().sort_values(ascending=False)
    n = len(s)
    if n == 0:
        return []
    if n < MIN_POOL_FOR_PCT:
        k = 1
    else:
        k = max(1, int(np.floor(n * pct)))
    # side arg kept for API compatibility; ranking already side-adjusted
    _ = side
    return list(s.head(k).index)


def equal_weight_lots(
    capital: float,
    price: float,
    size: float,
    n_names: int,
    gross_leverage: float = GROSS_LEVERAGE,
    max_lots: int = MAX_LOTS_PER_NAME,
) -> int:
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


# Equal-weight factors including ADX (higher ADX = stronger trend)
# FACTOR_COLS / DEFAULT_FACTOR_COLS defined near module params above.


def apply_signal_config(cfg: dict, profile_name: str = "custom") -> dict:
    """Apply signal-layer params (Donchian / select / rebalance / filter / factors).

    Mutates module globals used by compute_features and by backtests that
    re-bind from this module. Does not change risk overlay.
    """
    global ENTRY_WINDOW, SELECT_PCT, REBALANCE_EVERY_N_DAYS, BODY_ATR_MIN
    global USE_VOLUME_FILTER, FACTOR_COLS, _ACTIVE_SIGNAL_PROFILE

    c = dict(cfg)
    if "entry_window" in c:
        ENTRY_WINDOW = int(c["entry_window"])
    if "select_pct" in c:
        SELECT_PCT = float(c["select_pct"])
    if "rebalance_every_n_days" in c:
        REBALANCE_EVERY_N_DAYS = int(c["rebalance_every_n_days"])
    if "body_atr_min" in c:
        BODY_ATR_MIN = float(c["body_atr_min"])
    if "use_volume_filter" in c:
        USE_VOLUME_FILTER = bool(c["use_volume_filter"])
    if "factor_cols" in c and c["factor_cols"] is not None:
        FACTOR_COLS = list(c["factor_cols"])
    _ACTIVE_SIGNAL_PROFILE = str(profile_name)
    out = {
        "profile": _ACTIVE_SIGNAL_PROFILE,
        "entry_window": ENTRY_WINDOW,
        "select_pct": SELECT_PCT,
        "rebalance_every_n_days": REBALANCE_EVERY_N_DAYS,
        "body_atr_min": BODY_ATR_MIN,
        "use_volume_filter": USE_VOLUME_FILTER,
        "factor_cols": list(FACTOR_COLS),
    }
    SIGNAL_PROFILES[_ACTIVE_SIGNAL_PROFILE] = dict(out)
    return out


def apply_signal_profile(name: str) -> dict:
    key = str(name).strip().lower()
    if key not in SIGNAL_PROFILES:
        raise ValueError(f"Unknown signal profile {name!r}; choose from {sorted(SIGNAL_PROFILES)}")
    body = {k: v for k, v in SIGNAL_PROFILES[key].items() if k != "profile"}
    return apply_signal_config(body, profile_name=key)
