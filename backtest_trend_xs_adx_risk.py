# -*- coding: utf-8 -*-
"""Backtest: Trend-gated XS + ADX + fake-breakout + EW + risk overlay.

Risk only scales / blocks; signals unchanged. Compare vs trend_xs_adx_results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
sys.path.insert(0, str(BASE))

from strategies.trend_xs_adx_risk import (  # noqa: E402
    ADX_WINDOW,
    BODY_ATR_MIN,
    CAPITAL,
    COMMISSION_RATE,
    COMMODITY_SPECS,
    DD_FLAT_THRESHOLD,
    DD_FLAT_RECOVER_THRESHOLD,
    DD_HALF_THRESHOLD,
    DD_RECOVERY_THRESHOLD,
    ENABLE_DD_CIRCUIT,
    ENABLE_GROSS_LEVERAGE_CAP,
    ENABLE_VOL_TARGET,
    ENTRY_WINDOW,
    FACTOR_COLS,
    GROSS_LEVERAGE_CAP,
    MAX_LOTS_PER_NAME,
    MIN_HISTORY,
    REBALANCE_EVERY_N_DAYS,
    RISK_BASE_GROSS,
    RISK_PARAMS,
    RISK_PROFILES,
    SELECT_PCT,
    VOL_LOOKBACK,
    VOL_SCALE_MIN,
    VOL_SMA_WINDOW,
    VOL_TARGET_ANNUAL,
    apply_risk_profile,
    apply_signal_profile,
    SIGNAL_PROFILES,
    composite_scores,
    compute_features,
    dd_multiplier_and_state,
    effective_gross_leverage,
    equal_weight_lots,
    realized_vol_annual,
    select_names,
    vol_scale_factor,
)
import strategies.trend_xs_adx_risk as risk_mod  # noqa: E402

DATA_DIR = BASE / "data"
OUT_DIR_BY_PROFILE = {
    "tight": DATA_DIR / "trend_xs_adx_risk_results",
    "loose": DATA_DIR / "trend_xs_adx_risk_loose_results",
    "search_best": DATA_DIR / "trend_xs_adx_risk_search_best_results",
}
OUT_DIR = OUT_DIR_BY_PROFILE["tight"]
PRIOR_ADX_SUMMARY = DATA_DIR / "trend_xs_adx_results" / "summary.json"
PRIOR_TIGHT_SUMMARY = DATA_DIR / "trend_xs_adx_risk_results" / "summary.json"


def load_symbol(name: str, spec: dict) -> pd.DataFrame | None:
    path = DATA_DIR / spec["csv"]
    if not path.exists():
        print(f"[skip] missing {path}")
        return None
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["datetime"] = pd.to_datetime(df["datetime"].astype(str).str[:10])
    df = df.sort_values("datetime").drop_duplicates("datetime", keep="last")
    df = df.set_index("datetime")
    for col in ("open", "high", "low", "close", "volume", "open_interest"):
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < MIN_HISTORY:
        print(f"[skip] {name} too few bars: {len(df)}")
        return None
    feat = compute_features(df)
    feat["size"] = spec["size"]
    feat["pricetick"] = spec["pricetick"]
    feat["symbol"] = name
    return feat


def build_panel(frames: dict[str, pd.DataFrame]):
    all_dates = sorted(set().union(*[set(f.index) for f in frames.values()]))
    return pd.DatetimeIndex(all_dates), frames


def turnover_cost(price: float, lots: int, size: float, pricetick: float) -> float:
    if lots <= 0:
        return 0.0
    notional = abs(price) * size * lots
    commission = notional * COMMISSION_RATE
    slip = pricetick * size * lots
    return commission + slip


def run_backtest(frames: dict[str, pd.DataFrame]) -> dict:
    calendar, _ = build_panel(frames)
    symbols = sorted(frames.keys())

    start_i = 0
    for i, dt in enumerate(calendar):
        ready = sum(
            1
            for s in symbols
            if dt in frames[s].index and frames[s].index.get_loc(dt) >= MIN_HISTORY - 1
        )
        if ready >= max(4, len(symbols) // 2):
            start_i = i
            break

    positions: dict[str, dict] = {}
    equity_rows = []
    trade_rows = []
    rebalance_dates = []
    last_close = {s: np.nan for s in symbols}
    cum_realized = 0.0
    rebalance_countdown = 0
    filter_reject_count = 0
    enter_ok_long_days = 0
    enter_ok_short_days = 0

    # Risk state
    peak_equity = CAPITAL
    dd_state = "NORMAL"
    equity_rets: list[float] = []
    prev_equity = CAPITAL
    flat_force_closes = 0
    risk_event_rows = []

    def mark_mtm(dt: pd.Timestamp) -> float:
        mtm = 0.0
        for sym, pos in positions.items():
            if dt not in frames[sym].index:
                px = last_close[sym]
            else:
                px = float(frames[sym].loc[dt, "close"])
            if not np.isfinite(px) or not np.isfinite(pos["entry_price"]):
                continue
            mtm += (px - pos["entry_price"]) * pos["dir"] * pos["lots"] * pos["size"]
        return mtm

    def close_position(sym: str, dt: pd.Timestamp, price: float, reason: str):
        nonlocal cum_realized
        pos = positions.pop(sym, None)
        if not pos:
            return
        size = pos["size"]
        lots = pos["lots"]
        pnl = (price - pos["entry_price"]) * pos["dir"] * lots * size
        cost = turnover_cost(price, lots, size, pos["pricetick"])
        cum_realized += pnl - cost
        trade_rows.append(
            {
                "datetime": str(dt.date()),
                "symbol": sym,
                "action": "CLOSE",
                "direction": pos["dir"],
                "lots": lots,
                "price": price,
                "pnl": pnl,
                "cost": cost,
                "reason": reason,
            }
        )

    def open_position(
        sym: str,
        dt: pd.Timestamp,
        direction: int,
        lots: int,
        price: float,
        size: float,
        pricetick: float,
        reason: str,
    ):
        nonlocal cum_realized
        if lots <= 0:
            return
        cost = turnover_cost(price, lots, size, pricetick)
        cum_realized -= cost
        positions[sym] = {
            "dir": direction,
            "lots": lots,
            "entry_price": price,
            "entry_date": dt,
            "size": size,
            "pricetick": pricetick,
        }
        trade_rows.append(
            {
                "datetime": str(dt.date()),
                "symbol": sym,
                "action": "OPEN",
                "direction": direction,
                "lots": lots,
                "price": price,
                "pnl": 0.0,
                "cost": cost,
                "reason": reason,
            }
        )

    def gross_notional(dt: pd.Timestamp) -> float:
        total = 0.0
        for sym, pos in positions.items():
            if dt in frames[sym].index:
                px = float(frames[sym].loc[dt, "close"])
            else:
                px = last_close[sym]
            if not np.isfinite(px):
                continue
            total += abs(px) * pos["lots"] * pos["size"]
        return total

    for i in range(start_i, len(calendar)):
        dt = calendar[i]

        for s in symbols:
            if dt in frames[s].index:
                last_close[s] = float(frames[s].loc[dt, "close"])

        # Gate exits (signal layer unchanged)
        to_close = []
        for sym, pos in list(positions.items()):
            if dt not in frames[sym].index:
                continue
            row = frames[sym].loc[dt]
            if pos["dir"] > 0 and not bool(row["long_eligible"]):
                to_close.append((sym, float(row["close"]), "gate_exit_long"))
            elif pos["dir"] < 0 and not bool(row["short_eligible"]):
                to_close.append((sym, float(row["close"]), "gate_exit_short"))
        for sym, px, reason in to_close:
            close_position(sym, dt, px, reason)

        # Intra-day risk snapshot using pre-rebalance MTM (no lookahead on today's ret for vol)
        mtm_pre = mark_mtm(dt)
        equity_pre = CAPITAL + cum_realized + mtm_pre
        if equity_pre > peak_equity:
            peak_equity = equity_pre
        dd_frac = 0.0 if peak_equity <= 0 else max(0.0, (peak_equity - equity_pre) / peak_equity)
        dd_mult, dd_state = dd_multiplier_and_state(dd_frac, dd_state)

        # Vol scale from PRIOR equity returns only (exclude today)
        rvol = realized_vol_annual(equity_rets, risk_mod.VOL_LOOKBACK)
        vscale = vol_scale_factor(rvol)
        eff_gross = effective_gross_leverage(vscale, dd_mult)

        # FLAT: force-close all and block new entries
        if dd_state == "FLAT" and positions:
            for sym in list(positions.keys()):
                if dt in frames[sym].index:
                    px = float(frames[sym].loc[dt, "close"])
                else:
                    px = last_close[sym]
                if np.isfinite(px):
                    close_position(sym, dt, px, "dd_flat_force_close")
                    flat_force_closes += 1

        do_rebalance = rebalance_countdown <= 0
        if do_rebalance:
            rebalance_countdown = REBALANCE_EVERY_N_DAYS
            rebalance_dates.append(str(dt.date()))

            records = []
            for s in symbols:
                if dt not in frames[s].index:
                    continue
                r = frames[s].loc[dt]
                if pd.isna(r.get("donchian_high")) or pd.isna(r.get("atr")):
                    continue
                if pd.isna(r.get("adx")):
                    continue
                long_gate = bool(r["long_eligible"]) if pd.notna(r["long_eligible"]) else False
                short_gate = bool(r["short_eligible"]) if pd.notna(r["short_eligible"]) else False
                long_ok = bool(r["long_enter_ok"]) if pd.notna(r["long_enter_ok"]) else False
                short_ok = bool(r["short_enter_ok"]) if pd.notna(r["short_enter_ok"]) else False
                if long_gate and not long_ok:
                    filter_reject_count += 1
                if short_gate and not short_ok:
                    filter_reject_count += 1
                if long_ok:
                    enter_ok_long_days += 1
                if short_ok:
                    enter_ok_short_days += 1
                rec = {
                    "symbol": s,
                    "close": float(r["close"]),
                    "atr": float(r["atr"]),
                    "size": float(r["size"]),
                    "pricetick": float(r["pricetick"]),
                    "long_enter_ok": long_ok,
                    "short_enter_ok": short_ok,
                }
                for c in FACTOR_COLS:
                    rec[c] = float(r[c]) if c in r.index and pd.notna(r[c]) else np.nan
                records.append(rec)

            target: dict[str, int] = {}
            if records and dd_state != "FLAT" and eff_gross > 1e-12:
                snap = pd.DataFrame(records).set_index("symbol")
                long_pool = snap[snap["long_enter_ok"]]
                short_pool = snap[snap["short_enter_ok"]]

                long_scores = (
                    composite_scores(long_pool, FACTOR_COLS, side="long")
                    if len(long_pool)
                    else pd.Series(dtype=float)
                )
                short_scores = (
                    composite_scores(short_pool, FACTOR_COLS, side="short")
                    if len(short_pool)
                    else pd.Series(dtype=float)
                )

                long_sel = select_names(long_scores, "long", SELECT_PCT)
                short_sel = select_names(short_scores, "short", SELECT_PCT)
                both = set(long_sel) & set(short_sel)
                long_sel = [x for x in long_sel if x not in both]
                short_sel = [x for x in short_sel if x not in both]

                n_sel = len(long_sel) + len(short_sel)
                # Risk-scaled capital budget via effective gross leverage
                for s in long_sel:
                    lots = equal_weight_lots(
                        CAPITAL,
                        snap.loc[s, "close"],
                        snap.loc[s, "size"],
                        n_sel,
                        gross_leverage=eff_gross,
                    )
                    if lots > 0:
                        target[s] = lots
                for s in short_sel:
                    lots = equal_weight_lots(
                        CAPITAL,
                        snap.loc[s, "close"],
                        snap.loc[s, "size"],
                        n_sel,
                        gross_leverage=eff_gross,
                    )
                    if lots > 0:
                        target[s] = -lots

            # Close names not in target / wrong size / wrong side
            for sym in list(positions.keys()):
                want = target.get(sym, 0)
                cur = positions[sym]["dir"] * positions[sym]["lots"]
                if want == 0 or np.sign(want) != np.sign(cur) or abs(want) != abs(cur):
                    if dt in frames[sym].index:
                        px = float(frames[sym].loc[dt, "close"])
                    else:
                        px = last_close[sym]
                    close_position(sym, dt, px, "rebalance_close")

            # Opens blocked when FLAT (target empty)
            for sym, signed_lots in target.items():
                if sym in positions:
                    continue
                direction = 1 if signed_lots > 0 else -1
                lots = abs(signed_lots)
                # snap must exist if target non-empty
                px = float(frames[sym].loc[dt, "close"])
                size = float(frames[sym].loc[dt, "size"])
                pricetick = float(frames[sym].loc[dt, "pricetick"])
                open_position(
                    sym,
                    dt,
                    direction,
                    lots,
                    px,
                    size,
                    pricetick,
                    "rebalance_open",
                )

            risk_event_rows.append(
                {
                    "datetime": str(dt.date()),
                    "dd_frac": round(dd_frac, 6),
                    "dd_state": dd_state,
                    "dd_mult": dd_mult,
                    "realized_vol_ann": None if not np.isfinite(rvol) else round(float(rvol), 6),
                    "vol_scale": round(vscale, 6),
                    "eff_gross": round(eff_gross, 6),
                    "n_target": len(target),
                }
            )

        rebalance_countdown -= 1

        mtm = mark_mtm(dt)
        equity = CAPITAL + cum_realized + mtm
        if equity > peak_equity:
            peak_equity = equity
        dd_frac_eod = 0.0 if peak_equity <= 0 else max(0.0, (peak_equity - equity) / peak_equity)

        # Record return for next day's vol (after EOD equity known)
        if prev_equity > 0 and np.isfinite(equity):
            equity_rets.append((equity / prev_equity) - 1.0)
        prev_equity = equity

        n_long = sum(1 for p in positions.values() if p["dir"] > 0)
        n_short = sum(1 for p in positions.values() if p["dir"] < 0)
        gnot = gross_notional(dt)
        equity_rows.append(
            {
                "datetime": dt,
                "equity": equity,
                "realized": cum_realized,
                "mtm": mtm,
                "n_long": n_long,
                "n_short": n_short,
                "n_pos": len(positions),
                "dd_frac": dd_frac_eod,
                "dd_state": dd_state,
                "gross_notional": gnot,
                "gross_leverage": (gnot / equity) if equity > 0 else 0.0,
            }
        )

    eq = pd.DataFrame(equity_rows).set_index("datetime")
    trades = pd.DataFrame(trade_rows)
    risk_log = pd.DataFrame(risk_event_rows)

    if eq.empty:
        return {"error": "empty equity"}

    eq["ret"] = eq["equity"].pct_change().fillna(0.0)
    total_return = (eq["equity"].iloc[-1] / CAPITAL - 1.0) * 100.0
    n_days = len(eq)
    years = n_days / 252.0
    if years > 0 and eq["equity"].iloc[-1] > 0:
        ann = ((eq["equity"].iloc[-1] / CAPITAL) ** (1.0 / years) - 1.0) * 100.0
    else:
        ann = 0.0
    peak = eq["equity"].cummax()
    dd = (eq["equity"] - peak) / peak
    max_dd = float(dd.min() * 100.0)
    vol = float(eq["ret"].std())
    sharpe = float(eq["ret"].mean() / vol * np.sqrt(252)) if vol > 1e-12 else 0.0

    n_closes = int((trades["action"] == "CLOSE").sum()) if not trades.empty else 0
    n_opens = int((trades["action"] == "OPEN").sum()) if not trades.empty else 0
    close_pnls = (
        trades.loc[trades["action"] == "CLOSE", "pnl"] if not trades.empty else pd.Series(dtype=float)
    )
    win_rate = float((close_pnls > 0).mean() * 100.0) if len(close_pnls) else None

    days_half = int((eq["dd_state"] == "HALF").sum()) if "dd_state" in eq.columns else 0
    days_flat = int((eq["dd_state"] == "FLAT").sum()) if "dd_state" in eq.columns else 0
    avg_gross_lev = float(eq["gross_leverage"].mean()) if "gross_leverage" in eq.columns else None
    max_gross_lev = float(eq["gross_leverage"].max()) if "gross_leverage" in eq.columns else None

    return {
        "equity": eq,
        "trades": trades,
        "risk_log": risk_log,
        "rebalance_dates": rebalance_dates,
        "symbols": symbols,
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "days": n_days,
        "total_return_pct": round(total_return, 4),
        "annual_return_pct": round(ann, 4),
        "max_ddpercent": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "end_equity": round(float(eq["equity"].iloc[-1]), 2),
        "total_net_pnl": round(float(eq["equity"].iloc[-1] - CAPITAL), 2),
        "n_opens": n_opens,
        "n_closes": n_closes,
        "win_rate_pct": None if win_rate is None else round(win_rate, 2),
        "filter_reject_count": filter_reject_count,
        "enter_ok_long_hits": enter_ok_long_days,
        "enter_ok_short_hits": enter_ok_short_days,
        "flat_force_closes": flat_force_closes,
        "days_half": days_half,
        "days_flat": days_flat,
        "avg_gross_leverage": None if avg_gross_lev is None else round(avg_gross_lev, 4),
        "max_gross_leverage": None if max_gross_lev is None else round(max_gross_lev, 4),
        "params": {
            "entry_window": ENTRY_WINDOW,
            "adx_window": ADX_WINDOW,
            "select_pct": SELECT_PCT,
            "rebalance_every_n_days": REBALANCE_EVERY_N_DAYS,
            "capital": CAPITAL,
            "commission_rate": COMMISSION_RATE,
            "sizing": "equal_weight_then_risk_overlay",
            "max_lots_per_name": MAX_LOTS_PER_NAME,
            "body_atr_min": BODY_ATR_MIN,
            "vol_sma_window": VOL_SMA_WINDOW,
            "filter": "body_atr_and_volume_vs_prior_20d_sma",
            "factor_cols": list(FACTOR_COLS),
            "scoring": "equal_weight_robust_z; directional flipped for shorts; adx/low_vol positive both sides",
            "adx": "Wilder ADX(14) at signal-bar close (EOD-known)",
            "risk": dict(risk_mod.RISK_PARAMS),
        },
    }


def main(profile: str = "tight", signal_profile: str | None = None) -> None:
    global OUT_DIR
    profile = str(profile).strip().lower()
    apply_risk_profile(profile)
    if signal_profile:
        sp = apply_signal_profile(signal_profile)
        global ENTRY_WINDOW, SELECT_PCT, REBALANCE_EVERY_N_DAYS, BODY_ATR_MIN, FACTOR_COLS
        ENTRY_WINDOW = int(sp["entry_window"])
        SELECT_PCT = float(sp["select_pct"])
        REBALANCE_EVERY_N_DAYS = int(sp["rebalance_every_n_days"])
        BODY_ATR_MIN = float(sp["body_atr_min"])
        FACTOR_COLS = list(sp["factor_cols"])
        if hasattr(risk_mod, "USE_VOLUME_FILTER"):
            risk_mod.USE_VOLUME_FILTER = bool(sp["use_volume_filter"])
        import strategies.trend_xs_adx as _adx
        _adx.USE_VOLUME_FILTER = bool(sp["use_volume_filter"])
        print(f"Signal profile: {signal_profile} -> {sp}")
    # Re-bind names used in report strings from module after profile apply
    global ENABLE_VOL_TARGET, VOL_TARGET_ANNUAL, VOL_LOOKBACK, VOL_SCALE_MIN
    global ENABLE_GROSS_LEVERAGE_CAP, GROSS_LEVERAGE_CAP, RISK_BASE_GROSS
    global ENABLE_DD_CIRCUIT, DD_HALF_THRESHOLD, DD_FLAT_THRESHOLD
    global DD_RECOVERY_THRESHOLD, DD_FLAT_RECOVER_THRESHOLD, RISK_PARAMS
    ENABLE_VOL_TARGET = risk_mod.ENABLE_VOL_TARGET
    VOL_TARGET_ANNUAL = risk_mod.VOL_TARGET_ANNUAL
    VOL_LOOKBACK = risk_mod.VOL_LOOKBACK
    VOL_SCALE_MIN = risk_mod.VOL_SCALE_MIN
    ENABLE_GROSS_LEVERAGE_CAP = risk_mod.ENABLE_GROSS_LEVERAGE_CAP
    GROSS_LEVERAGE_CAP = risk_mod.GROSS_LEVERAGE_CAP
    RISK_BASE_GROSS = risk_mod.RISK_BASE_GROSS
    ENABLE_DD_CIRCUIT = risk_mod.ENABLE_DD_CIRCUIT
    DD_HALF_THRESHOLD = risk_mod.DD_HALF_THRESHOLD
    DD_FLAT_THRESHOLD = risk_mod.DD_FLAT_THRESHOLD
    DD_RECOVERY_THRESHOLD = risk_mod.DD_RECOVERY_THRESHOLD
    DD_FLAT_RECOVER_THRESHOLD = risk_mod.DD_FLAT_RECOVER_THRESHOLD
    RISK_PARAMS = dict(risk_mod.RISK_PARAMS)

    if signal_profile:
        OUT_DIR = DATA_DIR / f"trend_xs_signal_{signal_profile}_results"
    else:
        OUT_DIR = OUT_DIR_BY_PROFILE.get(profile, DATA_DIR / f"trend_xs_adx_risk_{profile}_results")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frames: dict[str, pd.DataFrame] = {}
    for name, spec in COMMODITY_SPECS.items():
        f = load_symbol(name, spec)
        if f is not None:
            frames[name] = f
            print(f"Loaded {name}: {len(f)} bars {f.index[0].date()} -> {f.index[-1].date()}")

    if len(frames) < 4:
        raise SystemExit(f"Need >=4 commodity series, got {len(frames)}")

    print(f"Universe ({len(frames)}): {', '.join(sorted(frames))}")
    print(f"Risk profile: {profile}")
    print(
        f"Risk: vol_target={ENABLE_VOL_TARGET}@{VOL_TARGET_ANNUAL} vol_floor={VOL_SCALE_MIN} "
        f"cap={ENABLE_GROSS_LEVERAGE_CAP}@{GROSS_LEVERAGE_CAP} "
        f"dd={ENABLE_DD_CIRCUIT} half>{DD_HALF_THRESHOLD} flat>{DD_FLAT_THRESHOLD} "
        f"recover HALF->NORMAL<={DD_RECOVERY_THRESHOLD} FLAT->HALF<={DD_FLAT_RECOVER_THRESHOLD}"
    )
    result = run_backtest(frames)
    if result.get("error"):
        raise SystemExit(result["error"])

    eq: pd.DataFrame = result["equity"]
    trades: pd.DataFrame = result["trades"]
    risk_log: pd.DataFrame = result["risk_log"]

    equity_path = OUT_DIR / "equity_curve.csv"
    eq.to_csv(equity_path, encoding="utf-8-sig")
    trades_path = OUT_DIR / "trades.csv"
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
    risk_path = OUT_DIR / "risk_rebalance_log.csv"
    risk_log.to_csv(risk_path, index=False, encoding="utf-8-sig")

    prior = None
    if PRIOR_ADX_SUMMARY.exists():
        prior = json.loads(PRIOR_ADX_SUMMARY.read_text(encoding="utf-8"))

    summary = {
        "strategy": "趋势门控+假突破过滤+截面等权(含ADX)+等权底仓+组合风控层",
        "strategy_en": "Trend-gated XS ADX EW + fake-breakout + vol-target/leverage-cap/DD circuit",
        "universe": result["symbols"],
        "n_universe": len(result["symbols"]),
        "start": result["start"],
        "end": result["end"],
        "days": result["days"],
        "total_return_pct": result["total_return_pct"],
        "annual_return_pct": result["annual_return_pct"],
        "max_ddpercent": result["max_ddpercent"],
        "sharpe_ratio": result["sharpe_ratio"],
        "end_equity": result["end_equity"],
        "total_net_pnl": result["total_net_pnl"],
        "n_opens": result["n_opens"],
        "n_closes": result["n_closes"],
        "win_rate_pct": result["win_rate_pct"],
        "n_rebalances": len(result["rebalance_dates"]),
        "filter_reject_count": result["filter_reject_count"],
        "enter_ok_long_hits": result["enter_ok_long_hits"],
        "enter_ok_short_hits": result["enter_ok_short_hits"],
        "flat_force_closes": result["flat_force_closes"],
        "days_half": result["days_half"],
        "days_flat": result["days_flat"],
        "avg_gross_leverage": result["avg_gross_leverage"],
        "max_gross_leverage": result["max_gross_leverage"],
        "params": result["params"],
        "risk_profile": profile,
        "prior_adx_40": {
            "total_return_pct": prior.get("total_return_pct") if prior else None,
            "annual_return_pct": prior.get("annual_return_pct") if prior else None,
            "max_ddpercent": prior.get("max_ddpercent") if prior else None,
            "sharpe_ratio": prior.get("sharpe_ratio") if prior else None,
            "end_equity": prior.get("end_equity") if prior else None,
            "n_opens": prior.get("n_opens") if prior else None,
            "win_rate_pct": prior.get("win_rate_pct") if prior else None,
            "path": str(PRIOR_ADX_SUMMARY),
        },
        "prior_tight_risk": (
            None
            if profile == "tight" or not PRIOR_TIGHT_SUMMARY.exists()
            else {
                k: json.loads(PRIOR_TIGHT_SUMMARY.read_text(encoding="utf-8")).get(k)
                for k in (
                    "total_return_pct",
                    "annual_return_pct",
                    "max_ddpercent",
                    "sharpe_ratio",
                    "avg_gross_leverage",
                    "max_gross_leverage",
                    "days_half",
                    "days_flat",
                    "end_equity",
                    "n_opens",
                )
            }
        ),
        "equity_csv": str(equity_path),
        "trades_csv": str(trades_path),
        "risk_log_csv": str(risk_path),
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"Trend-gated XS + fake-breakout + EW + ADX(14) + RISK overlay [{profile}]",
        f"universe ({len(result['symbols'])}): {', '.join(result['symbols'])}",
        f"range: {result['start']} -> {result['end']}  days={result['days']}",
        f"rebalance: every {REBALANCE_EVERY_N_DAYS} trading days | select_pct={SELECT_PCT}",
        f"capital={CAPITAL} | commission={COMMISSION_RATE} | slippage=1 tick",
        f"base_gross={RISK_BASE_GROSS} | vol_target={ENABLE_VOL_TARGET}@{VOL_TARGET_ANNUAL} lookback={VOL_LOOKBACK}",
        f"leverage_cap={ENABLE_GROSS_LEVERAGE_CAP}@{GROSS_LEVERAGE_CAP}",
        f"dd_circuit={ENABLE_DD_CIRCUIT} half>{DD_HALF_THRESHOLD} flat>{DD_FLAT_THRESHOLD} "
        f"HALF->NORMAL<={DD_RECOVERY_THRESHOLD} FLAT->HALF<={DD_FLAT_RECOVER_THRESHOLD} vol_floor={VOL_SCALE_MIN}",
        f"filter: body/ATR>={BODY_ATR_MIN} AND volume>prior_{VOL_SMA_WINDOW}d_sma (plus Donchian gate)",
        f"factors: {', '.join(FACTOR_COLS)}",
        "",
        f"total_return: {result['total_return_pct']:.4f}%",
        f"annual_return: {result['annual_return_pct']:.4f}%",
        f"max_drawdown: {result['max_ddpercent']:.4f}%",
        f"Sharpe: {result['sharpe_ratio']:.4f}",
        f"end_equity: {result['end_equity']:.2f}  net_pnl: {result['total_net_pnl']:.2f}",
        f"opens: {result['n_opens']}  closes: {result['n_closes']}  win_rate(closes): {result['win_rate_pct']}%",
        f"rebalances: {len(result['rebalance_dates'])}",
        f"filter_rejects: {result['filter_reject_count']}",
        f"dd days HALF/FLAT: {result['days_half']}/{result['days_flat']}  flat_force_closes: {result['flat_force_closes']}",
        f"avg/max gross leverage: {result['avg_gross_leverage']} / {result['max_gross_leverage']}",
        "",
    ]
    if prior:
        lines += [
            "Compare vs prior ADX+40 EW (trend_xs_adx_results):",
            f"  prior total_return: {prior.get('total_return_pct')}%  vs  {result['total_return_pct']}%",
            f"  prior annual: {prior.get('annual_return_pct')}%  vs  {result['annual_return_pct']}%",
            f"  prior max_dd: {prior.get('max_ddpercent')}%  vs  {result['max_ddpercent']}%",
            f"  prior Sharpe: {prior.get('sharpe_ratio')}  vs  {result['sharpe_ratio']}",
            f"  prior opens: {prior.get('n_opens')}  vs  {result['n_opens']}",
            "",
        ]
    if profile != "tight" and PRIOR_TIGHT_SUMMARY.exists():
        tight = json.loads(PRIOR_TIGHT_SUMMARY.read_text(encoding="utf-8"))
        lines += [
            "Compare vs TIGHT risk (trend_xs_adx_risk_results):",
            f"  tight total_return: {tight.get('total_return_pct')}%  vs  {result['total_return_pct']}%",
            f"  tight annual: {tight.get('annual_return_pct')}%  vs  {result['annual_return_pct']}%",
            f"  tight max_dd: {tight.get('max_ddpercent')}%  vs  {result['max_ddpercent']}%",
            f"  tight Sharpe: {tight.get('sharpe_ratio')}  vs  {result['sharpe_ratio']}",
            f"  tight avg/max gross: {tight.get('avg_gross_leverage')}/{tight.get('max_gross_leverage')}  vs  "
            f"{result['avg_gross_leverage']}/{result['max_gross_leverage']}",
            f"  tight HALF/FLAT days: {tight.get('days_half')}/{tight.get('days_flat')}  vs  "
            f"{result['days_half']}/{result['days_flat']}",
            "",
        ]
    lines += [
        "Caveats:",
        "- Same Sina main-force continuous caveats as ADX baseline.",
        "- Vol scale uses prior equity returns only (no same-day lookahead).",
        "- Gross cap applied after vol scale; DD mult last.",
        "- Past backtest != future expectation.",
    ]
    report_path = OUT_DIR / "report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSummary: {summary_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Trend XS ADX risk overlay backtest")
    ap.add_argument(
        "--profile",
        choices=sorted(RISK_PROFILES.keys()),
        default="tight",
        help="Risk profile: tight (default prior) or loose (higher DD thresholds / vol target)",
    )
    ap.add_argument(
        "--signal-profile",
        default=None,
        help="Optional signal profile (e.g. baseline, signal_best)",
    )
    args = ap.parse_args()
    main(profile=args.profile, signal_profile=args.signal_profile)
