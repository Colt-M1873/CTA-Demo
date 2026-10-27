# -*- coding: utf-8 -*-
"""Trend-gated XS multifactor with XGBoost cross-sectional scoring.

Donchian trend gate stays rule-based. XGBoost only replaces equal-weight
factor scoring inside same-direction eligible pools (walk-forward).

Retune (2026-10-27): 20-commodity universe, 20-trading-day rebalance/label,
higher train readiness. Legacy 5d 12-name results remain under
data/trend_xs_xgb_results/; use backtest_trend_xs_xgb.py with pinned 5d
overrides to reproduce. New default entry: backtest_trend_xs_xgb_20d.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from strategies.trend_xs_multifactor import (  # re-export shared pieces
    ATR_WINDOW,
    CAPITAL,
    COMMISSION_RATE,
    COMMODITY_SPECS,
    ENTRY_WINDOW,
    FACTOR_COLS,
    FINANCIAL_EXCLUDE,
    MAX_LOTS_PER_NAME,
    MIN_HISTORY,
    MIN_POOL_FOR_PCT,
    MOM_WINDOWS,
    OI_WINDOW,
    RISK_FRAC_PER_NAME,
    SELECT_PCT,
    VOL_WINDOW,
    atr_lots,
    composite_scores,
    compute_features,
    robust_zscore,
    select_names,
    true_range,
)

# --- XGB-specific knobs (retuned for data scale; independent of EW baseline) ---
# Multifactor EW baseline keeps REBALANCE_EVERY_N_DAYS=5; XGB uses 20d.
REBALANCE_EVERY_N_DAYS_XGB = 20
HORIZON_DAYS = 20  # label = forward return over rebalance horizon
MIN_TRAIN_SAMPLES = 1500  # fall back to equal-weight until ready
MIN_TRAIN_REBALANCES = 100  # need enough past rebalance dates with labels
RETRAIN_EVERY_N_REBALANCES = 1  # retrain each rebalance (expanding window)
XGB_FEATURE_COLS = list(FACTOR_COLS) + ["channel_pos"]  # + cheap extra, leak-free

# Legacy 5d preset (for reproducing data/trend_xs_xgb_results/)
LEGACY_5D = {
    "horizon_days": 5,
    "rebalance_every_n_days": 5,
    "min_train_samples": 200,
    "min_train_rebalances": 50,
}

XGB_PARAMS = {
    "n_estimators": 80,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "min_child_weight": 5,
    "objective": "reg:squarederror",
    "n_jobs": 2,
    "random_state": 42,
    "verbosity": 0,
}


def add_xgb_extras(df: pd.DataFrame) -> pd.DataFrame:
    """Add leak-free extras on top of compute_features output.

    channel_pos: close location in prior-bar Donchian channel [0,1]-ish.
    """
    out = df.copy()
    hi = out["donchian_high"]
    lo = out["donchian_low"]
    width = (hi - lo).replace(0, np.nan)
    out["channel_pos"] = ((out["close"] - lo) / width).clip(-1, 2)
    return out


def forward_return_at(frame: pd.DataFrame, dt: pd.Timestamp, horizon: int = HORIZON_DAYS) -> float:
    """Close-to-close return from dt to dt+horizon bars on this symbol's index.

    Returns nan if not enough future bars (caller must only use when known).
    """
    if dt not in frame.index:
        return float("nan")
    loc = frame.index.get_loc(dt)
    if isinstance(loc, slice):
        return float("nan")
    if isinstance(loc, np.ndarray):
        loc = int(loc[0])
    j = loc + horizon
    if j >= len(frame.index):
        return float("nan")
    c0 = float(frame.iloc[loc]["close"])
    c1 = float(frame.iloc[j]["close"])
    if not np.isfinite(c0) or not np.isfinite(c1) or c0 == 0:
        return float("nan")
    return c1 / c0 - 1.0


@dataclass
class TrainRow:
    date: pd.Timestamp
    symbol: str
    features: dict[str, float]
    y: float  # forward return; nan until labelable


class ExpandingXGBScorer:
    """Walk-forward expanding-window XGBRegressor for cross-section scores.

    Label: regression on next-horizon close-to-close return (default 20d).
    At rebalance t, rank eligible names by predicted return
    (longs = high pred, shorts = low pred).
    """

    def __init__(
        self,
        feature_cols: Iterable[str] = XGB_FEATURE_COLS,
        min_train_samples: int = MIN_TRAIN_SAMPLES,
        min_train_rebalances: int = MIN_TRAIN_REBALANCES,
        horizon: int = HORIZON_DAYS,
        params: dict | None = None,
    ):
        self.feature_cols = list(feature_cols)
        self.min_train_samples = min_train_samples
        self.min_train_rebalances = min_train_rebalances
        self.horizon = horizon
        self.params = dict(params or XGB_PARAMS)
        self._history: list[TrainRow] = []
        self._model = None
        self._n_rebalances_seen = 0
        self._n_ml_scores = 0
        self._n_fallback_scores = 0
        self._last_mode = "fallback"
        self._feature_importance: dict[str, float] = {}

    def record_features(self, dt: pd.Timestamp, snap: pd.DataFrame) -> None:
        """Store today's feature rows; y filled later when horizon elapses."""
        self._n_rebalances_seen += 1
        for sym, row in snap.iterrows():
            feats = {}
            ok = True
            for c in self.feature_cols:
                v = row.get(c, np.nan)
                if pd.isna(v) or not np.isfinite(float(v)):
                    ok = False
                    break
                feats[c] = float(v)
            if not ok:
                continue
            self._history.append(TrainRow(date=dt, symbol=str(sym), features=feats, y=float("nan")))

    def label_past(self, frames: dict[str, pd.DataFrame], asof: pd.Timestamp) -> None:
        """Fill y for history rows whose forward window ends on/before asof."""
        for row in self._history:
            if np.isfinite(row.y):
                continue
            fr = frames.get(row.symbol)
            if fr is None or row.date not in fr.index:
                continue
            loc = fr.index.get_loc(row.date)
            if isinstance(loc, (slice, np.ndarray)):
                continue
            j = loc + self.horizon
            if j >= len(fr.index):
                continue
            end_dt = fr.index[j]
            if end_dt > asof:
                continue  # label not yet known at asof
            y = forward_return_at(fr, row.date, self.horizon)
            if np.isfinite(y):
                row.y = float(y)

    def _train_matrix(self, asof: pd.Timestamp) -> tuple[np.ndarray, np.ndarray, int] | None:
        """Build X, y from labeled rows with date < asof (strict)."""
        xs, ys, dates = [], [], set()
        for row in self._history:
            if row.date >= asof:
                continue
            if not np.isfinite(row.y):
                continue
            xs.append([row.features[c] for c in self.feature_cols])
            ys.append(row.y)
            dates.add(row.date)
        if len(xs) < self.min_train_samples or len(dates) < self.min_train_rebalances:
            return None
        return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float), len(dates)

    def fit_if_ready(self, asof: pd.Timestamp) -> bool:
        mat = self._train_matrix(asof)
        if mat is None:
            self._model = None
            return False
        X, y, _n_dates = mat
        try:
            from xgboost import XGBRegressor
        except ImportError as e:
            raise SystemExit("xgboost not installed in venv") from e
        model = XGBRegressor(**self.params)
        model.fit(X, y)
        self._model = model
        try:
            imp = model.feature_importances_
            self._feature_importance = {
                c: float(imp[i]) for i, c in enumerate(self.feature_cols)
            }
        except Exception:
            pass
        return True

    def score_pool(self, pool: pd.DataFrame) -> tuple[pd.Series, str]:
        """Return scores for pool index + mode ('xgb'|'fallback').

        Higher score => prefer for longs; lower => prefer for shorts.
        """
        if pool is None or len(pool) == 0:
            return pd.Series(dtype=float), "fallback"

        if self._model is None:
            self._n_fallback_scores += 1
            self._last_mode = "fallback"
            return composite_scores(pool, FACTOR_COLS), "fallback"

        rows = []
        idx = []
        for sym, row in pool.iterrows():
            vals = []
            good = True
            for c in self.feature_cols:
                v = row.get(c, np.nan)
                if pd.isna(v) or not np.isfinite(float(v)):
                    good = False
                    break
                vals.append(float(v))
            if good:
                rows.append(vals)
                idx.append(sym)
        if len(rows) < 1:
            self._n_fallback_scores += 1
            self._last_mode = "fallback"
            return composite_scores(pool, FACTOR_COLS), "fallback"

        pred = self._model.predict(np.asarray(rows, dtype=float))
        scores = pd.Series(pred, index=idx, dtype=float)
        scores = scores.reindex(pool.index)
        self._n_ml_scores += 1
        self._last_mode = "xgb"
        return scores, "xgb"

    def stats(self) -> dict:
        labeled = sum(1 for r in self._history if np.isfinite(r.y))
        return {
            "n_history_rows": len(self._history),
            "n_labeled_rows": labeled,
            "n_rebalances_seen": self._n_rebalances_seen,
            "n_ml_score_calls": self._n_ml_scores,
            "n_fallback_score_calls": self._n_fallback_scores,
            "last_mode": self._last_mode,
            "feature_importance": self._feature_importance,
            "min_train_samples": self.min_train_samples,
            "min_train_rebalances": self.min_train_rebalances,
            "horizon_days": self.horizon,
            "feature_cols": list(self.feature_cols),
            "xgb_params": dict(self.params),
        }
