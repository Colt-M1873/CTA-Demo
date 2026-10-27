# -*- coding: utf-8 -*-
"""Trend-gated XS + ADX + fake-breakout + EW base + portfolio risk overlay.

Signals / ADX / filter / selection unchanged from trend_xs_adx.
Risk layer only scales gross exposure or blocks new entries / forces flat.

Two named profiles (see RISK_PROFILES):
- tight (default module constants; prior run): vol 10%, cap 0.70,
  HALF>10% FLAT>15%, recover HALF→NORMAL @<=5%, FLAT→HALF @<=10%.
- search_best: vol 15%, floor 0.40, cap 0.80, HALF>15% FLAT>25% (grid-search winner by Sharpe).
- loose: vol 12%, softer vol floor, cap 0.80,
  HALF>15% FLAT>25%, recover HALF→NORMAL @<=10%, FLAT→HALF @<=15%.

Call apply_risk_profile("tight"|"loose") before backtest, or pass overrides
into the helper functions.
"""

from __future__ import annotations

from strategies.trend_xs_adx import *  # noqa: F401,F403
from strategies.trend_xs_adx import (  # noqa: F401 — explicit for importers
    ADX_WINDOW,
    BODY_ATR_MIN,
    CAPITAL,
    COMMISSION_RATE,
    COMMODITY_SPECS,
    DEFAULT_FACTOR_COLS,
    DIRECTIONAL_FACTORS,
    ENTRY_WINDOW,
    FACTOR_COLS,
    FINANCIAL_EXCLUDE,
    MAX_LOTS_PER_NAME,
    MIN_HISTORY,
    MIN_POOL_FOR_PCT,
    MOM_WINDOWS,
    OI_WINDOW,
    REBALANCE_EVERY_N_DAYS,
    SELECT_PCT,
    SIGNAL_PROFILES,
    USE_VOLUME_FILTER,
    VOL_SMA_WINDOW,
    VOL_WINDOW,
    Position,
    adx_wilder,
    apply_signal_config,
    apply_signal_profile,
    composite_scores,
    compute_features,
    equal_weight_lots,
    robust_zscore,
    select_names,
    true_range,
    wilder_rma,
)

# ---------------------------------------------------------------------------
# Risk overlay params — module defaults = TIGHT (prior documented run)
# ---------------------------------------------------------------------------

RISK_BASE_GROSS = 1.0

ENABLE_VOL_TARGET = True
VOL_TARGET_ANNUAL = 0.10
VOL_LOOKBACK = 20
VOL_SCALE_MIN = 0.10
VOL_SCALE_MAX = 1.50

ENABLE_GROSS_LEVERAGE_CAP = True
GROSS_LEVERAGE_CAP = 0.70

ENABLE_DD_CIRCUIT = True
DD_HALF_THRESHOLD = 0.10
DD_FLAT_THRESHOLD = 0.15
DD_RECOVERY_THRESHOLD = 0.05
# FLAT→HALF uses DD_FLAT_RECOVER_THRESHOLD (defaults to DD_HALF_THRESHOLD for tight).
DD_FLAT_RECOVER_THRESHOLD = 0.10

GROSS_LEVERAGE = RISK_BASE_GROSS

RISK_PROFILES = {
    "tight": {
        "enable_vol_target": True,
        "vol_target_annual": 0.10,
        "vol_lookback": 20,
        "vol_scale_min": 0.10,
        "vol_scale_max": 1.50,
        "enable_gross_leverage_cap": True,
        "gross_leverage_cap": 0.70,
        "risk_base_gross": 1.0,
        "enable_dd_circuit": True,
        "dd_half_threshold": 0.10,
        "dd_flat_threshold": 0.15,
        "dd_recovery_threshold": 0.05,
        "dd_flat_recover_threshold": 0.10,
        "dd_recovery_rule": (
            "Escalate: DD>10%→HALF(0.5), DD>15%→FLAT(0, force close, no new). "
            "De-escalate hysteresis: FLAT→HALF when DD<=10%; HALF→NORMAL when DD<=5%."
        ),
    },
    "loose": {
        "enable_vol_target": True,
        "vol_target_annual": 0.12,
        "vol_lookback": 20,
        "vol_scale_min": 0.25,
        "vol_scale_max": 1.50,
        "enable_gross_leverage_cap": True,
        "gross_leverage_cap": 0.80,
        "risk_base_gross": 1.0,
        "enable_dd_circuit": True,
        "dd_half_threshold": 0.15,
        "dd_flat_threshold": 0.25,
        "dd_recovery_threshold": 0.10,
        "dd_flat_recover_threshold": 0.15,
        "dd_recovery_rule": (
            "Escalate: DD>15%→HALF(0.5), DD>25%→FLAT(0, force close, no new). "
            "De-escalate hysteresis: FLAT→HALF when DD<=15%; HALF→NORMAL when DD<=10%."
        ),
    },
    "search_best": {
        "enable_vol_target": True,
        "vol_target_annual": 0.15,
        "vol_lookback": 20,
        "vol_scale_min": 0.40,
        "vol_scale_max": 1.50,
        "enable_gross_leverage_cap": True,
        "gross_leverage_cap": 0.80,
        "risk_base_gross": 1.0,
        "enable_dd_circuit": True,
        "dd_half_threshold": 0.15,
        "dd_flat_threshold": 0.25,
        "dd_recovery_threshold": 0.10,
        "dd_flat_recover_threshold": 0.15,
        "dd_recovery_rule": (
            "Escalate: DD>15%→HALF(0.5), DD>25%→FLAT(0, force close, no new). "
            "De-escalate hysteresis: FLAT→HALF when DD<=15%; HALF→NORMAL when DD<=10%. "
            "Search winner: vol_target=15%, floor=0.40, cap=0.80."
        ),
    },
}

_ACTIVE_PROFILE = "tight"


def _sync_risk_params_dict() -> dict:
    global RISK_PARAMS
    RISK_PARAMS = {
        "profile": _ACTIVE_PROFILE,
        "enable_vol_target": ENABLE_VOL_TARGET,
        "vol_target_annual": VOL_TARGET_ANNUAL,
        "vol_lookback": VOL_LOOKBACK,
        "vol_scale_min": VOL_SCALE_MIN,
        "vol_scale_max": VOL_SCALE_MAX,
        "enable_gross_leverage_cap": ENABLE_GROSS_LEVERAGE_CAP,
        "gross_leverage_cap": GROSS_LEVERAGE_CAP,
        "risk_base_gross": RISK_BASE_GROSS,
        "enable_dd_circuit": ENABLE_DD_CIRCUIT,
        "dd_half_threshold": DD_HALF_THRESHOLD,
        "dd_flat_threshold": DD_FLAT_THRESHOLD,
        "dd_recovery_threshold": DD_RECOVERY_THRESHOLD,
        "dd_flat_recover_threshold": DD_FLAT_RECOVER_THRESHOLD,
        "dd_recovery_rule": (
            f"Escalate: DD>{DD_HALF_THRESHOLD:.0%}→HALF(0.5), "
            f"DD>{DD_FLAT_THRESHOLD:.0%}→FLAT(0, force close, no new). "
            f"De-escalate hysteresis: FLAT→HALF when DD<={DD_FLAT_RECOVER_THRESHOLD:.0%}; "
            f"HALF→NORMAL when DD<={DD_RECOVERY_THRESHOLD:.0%}."
        ),
    }
    return RISK_PARAMS


def apply_risk_profile(name: str) -> dict:
    """Set module-level risk globals from RISK_PROFILES[name]. Returns RISK_PARAMS."""
    global RISK_BASE_GROSS
    global ENABLE_VOL_TARGET, VOL_TARGET_ANNUAL, VOL_LOOKBACK, VOL_SCALE_MIN, VOL_SCALE_MAX
    global ENABLE_GROSS_LEVERAGE_CAP, GROSS_LEVERAGE_CAP, GROSS_LEVERAGE
    global ENABLE_DD_CIRCUIT, DD_HALF_THRESHOLD, DD_FLAT_THRESHOLD
    global DD_RECOVERY_THRESHOLD, DD_FLAT_RECOVER_THRESHOLD
    global _ACTIVE_PROFILE

    key = str(name).strip().lower()
    if key not in RISK_PROFILES:
        raise ValueError(f"Unknown risk profile {name!r}; choose from {sorted(RISK_PROFILES)}")
    p = RISK_PROFILES[key]
    ENABLE_VOL_TARGET = bool(p["enable_vol_target"])
    VOL_TARGET_ANNUAL = float(p["vol_target_annual"])
    VOL_LOOKBACK = int(p["vol_lookback"])
    VOL_SCALE_MIN = float(p["vol_scale_min"])
    VOL_SCALE_MAX = float(p["vol_scale_max"])
    ENABLE_GROSS_LEVERAGE_CAP = bool(p["enable_gross_leverage_cap"])
    GROSS_LEVERAGE_CAP = float(p["gross_leverage_cap"])
    RISK_BASE_GROSS = float(p["risk_base_gross"])
    GROSS_LEVERAGE = RISK_BASE_GROSS
    ENABLE_DD_CIRCUIT = bool(p["enable_dd_circuit"])
    DD_HALF_THRESHOLD = float(p["dd_half_threshold"])
    DD_FLAT_THRESHOLD = float(p["dd_flat_threshold"])
    DD_RECOVERY_THRESHOLD = float(p["dd_recovery_threshold"])
    DD_FLAT_RECOVER_THRESHOLD = float(p["dd_flat_recover_threshold"])
    _ACTIVE_PROFILE = key
    return _sync_risk_params_dict()



def apply_risk_config(cfg: dict, profile_name: str = "custom") -> dict:
    """Apply an arbitrary risk-param dict (keys as in RISK_PROFILES values).

    Used by the search script; also registers a transient profile name.
    Missing keys keep current module globals.
    """
    global RISK_BASE_GROSS
    global ENABLE_VOL_TARGET, VOL_TARGET_ANNUAL, VOL_LOOKBACK, VOL_SCALE_MIN, VOL_SCALE_MAX
    global ENABLE_GROSS_LEVERAGE_CAP, GROSS_LEVERAGE_CAP, GROSS_LEVERAGE
    global ENABLE_DD_CIRCUIT, DD_HALF_THRESHOLD, DD_FLAT_THRESHOLD
    global DD_RECOVERY_THRESHOLD, DD_FLAT_RECOVER_THRESHOLD
    global _ACTIVE_PROFILE

    c = dict(cfg)
    if "enable_vol_target" in c:
        ENABLE_VOL_TARGET = bool(c["enable_vol_target"])
    if "vol_target_annual" in c:
        VOL_TARGET_ANNUAL = float(c["vol_target_annual"])
    if "vol_lookback" in c:
        VOL_LOOKBACK = int(c["vol_lookback"])
    if "vol_scale_min" in c:
        VOL_SCALE_MIN = float(c["vol_scale_min"])
    if "vol_scale_max" in c:
        VOL_SCALE_MAX = float(c["vol_scale_max"])
    if "enable_gross_leverage_cap" in c:
        ENABLE_GROSS_LEVERAGE_CAP = bool(c["enable_gross_leverage_cap"])
    if "gross_leverage_cap" in c:
        GROSS_LEVERAGE_CAP = float(c["gross_leverage_cap"])
    if "risk_base_gross" in c:
        RISK_BASE_GROSS = float(c["risk_base_gross"])
        GROSS_LEVERAGE = RISK_BASE_GROSS
    if "enable_dd_circuit" in c:
        ENABLE_DD_CIRCUIT = bool(c["enable_dd_circuit"])
    if "dd_half_threshold" in c:
        DD_HALF_THRESHOLD = float(c["dd_half_threshold"])
    if "dd_flat_threshold" in c:
        DD_FLAT_THRESHOLD = float(c["dd_flat_threshold"])
    if "dd_recovery_threshold" in c:
        DD_RECOVERY_THRESHOLD = float(c["dd_recovery_threshold"])
    if "dd_flat_recover_threshold" in c:
        DD_FLAT_RECOVER_THRESHOLD = float(c["dd_flat_recover_threshold"])
    _ACTIVE_PROFILE = str(profile_name)
    # Keep a copy under RISK_PROFILES for CLI reuse when name is search_best etc.
    RISK_PROFILES[_ACTIVE_PROFILE] = {
        "enable_vol_target": ENABLE_VOL_TARGET,
        "vol_target_annual": VOL_TARGET_ANNUAL,
        "vol_lookback": VOL_LOOKBACK,
        "vol_scale_min": VOL_SCALE_MIN,
        "vol_scale_max": VOL_SCALE_MAX,
        "enable_gross_leverage_cap": ENABLE_GROSS_LEVERAGE_CAP,
        "gross_leverage_cap": GROSS_LEVERAGE_CAP,
        "risk_base_gross": RISK_BASE_GROSS,
        "enable_dd_circuit": ENABLE_DD_CIRCUIT,
        "dd_half_threshold": DD_HALF_THRESHOLD,
        "dd_flat_threshold": DD_FLAT_THRESHOLD,
        "dd_recovery_threshold": DD_RECOVERY_THRESHOLD,
        "dd_flat_recover_threshold": DD_FLAT_RECOVER_THRESHOLD,
        "dd_recovery_rule": (
            f"Escalate: DD>{DD_HALF_THRESHOLD:.0%}→HALF(0.5), "
            f"DD>{DD_FLAT_THRESHOLD:.0%}→FLAT(0, force close, no new). "
            f"De-escalate hysteresis: FLAT→HALF when DD<={DD_FLAT_RECOVER_THRESHOLD:.0%}; "
            f"HALF→NORMAL when DD<={DD_RECOVERY_THRESHOLD:.0%}."
        ),
    }
    return _sync_risk_params_dict()


RISK_PARAMS = _sync_risk_params_dict()


def realized_vol_annual(returns, lookback: int | None = None) -> float:
    """Annualized stdev of the last `lookback` daily returns. NaN if insufficient."""
    import numpy as np

    if lookback is None:
        lookback = VOL_LOOKBACK
    if returns is None:
        return float("nan")
    arr = np.asarray(list(returns)[-lookback:], dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) < max(5, lookback // 2):
        return float("nan")
    vol = float(np.std(arr, ddof=1))
    if vol < 1e-12:
        return float("nan")
    return vol * float(np.sqrt(252.0))


def vol_scale_factor(
    realized_ann: float,
    target: float | None = None,
    lo: float | None = None,
    hi: float | None = None,
    enabled: bool | None = None,
) -> float:
    """target / realized, clipped. 1.0 if disabled or realized unknown."""
    import math

    if target is None:
        target = VOL_TARGET_ANNUAL
    if lo is None:
        lo = VOL_SCALE_MIN
    if hi is None:
        hi = VOL_SCALE_MAX
    if enabled is None:
        enabled = ENABLE_VOL_TARGET
    if not enabled:
        return 1.0
    if realized_ann is None or not math.isfinite(realized_ann) or realized_ann <= 0:
        return 1.0
    raw = float(target) / float(realized_ann)
    return float(max(lo, min(hi, raw)))


def dd_multiplier_and_state(
    dd_from_peak: float,
    prev_state: str,
    *,
    enabled: bool | None = None,
    half_th: float | None = None,
    flat_th: float | None = None,
    recovery_th: float | None = None,
    flat_recover_th: float | None = None,
) -> tuple[float, str]:
    """Return (size_mult, new_state) with hysteresis.

    dd_from_peak: positive fraction, e.g. 0.12 means -12% from peak.
    prev_state: 'NORMAL' | 'HALF' | 'FLAT'
    """
    if enabled is None:
        enabled = ENABLE_DD_CIRCUIT
    if half_th is None:
        half_th = DD_HALF_THRESHOLD
    if flat_th is None:
        flat_th = DD_FLAT_THRESHOLD
    if recovery_th is None:
        recovery_th = DD_RECOVERY_THRESHOLD
    if flat_recover_th is None:
        flat_recover_th = DD_FLAT_RECOVER_THRESHOLD

    if not enabled:
        return 1.0, "NORMAL"

    dd = max(0.0, float(dd_from_peak))
    state = prev_state if prev_state in ("NORMAL", "HALF", "FLAT") else "NORMAL"

    # Escalate aggressively
    if dd > flat_th:
        state = "FLAT"
    elif dd > half_th:
        if state == "NORMAL":
            state = "HALF"
        # FLAT stays FLAT until recovery (handled below)

    # De-escalate with hysteresis (less sticky when recover thresholds are higher)
    if state == "FLAT" and dd <= flat_recover_th:
        state = "HALF"
    if state == "HALF" and dd <= recovery_th:
        state = "NORMAL"

    mult = {"NORMAL": 1.0, "HALF": 0.5, "FLAT": 0.0}[state]
    return mult, state


def effective_gross_leverage(
    vol_scale: float,
    dd_mult: float,
    *,
    base_gross: float | None = None,
    cap: float | None = None,
    enable_cap: bool | None = None,
) -> float:
    """Combine vol targeting, leverage cap, and DD multiplier.

    gross = min(base_gross * vol_scale, cap_if_enabled) * dd_mult
    """
    if base_gross is None:
        base_gross = RISK_BASE_GROSS
    if cap is None:
        cap = GROSS_LEVERAGE_CAP
    if enable_cap is None:
        enable_cap = ENABLE_GROSS_LEVERAGE_CAP
    raw = float(base_gross) * float(vol_scale)
    if enable_cap:
        raw = min(raw, float(cap))
    return max(0.0, raw * float(dd_mult))
