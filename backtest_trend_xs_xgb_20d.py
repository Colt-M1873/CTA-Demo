# -*- coding: utf-8 -*-
"""Backtest: Trend-gated + XS XGBoost (20d retune).

- Universe: 20 commodities from COMMODITY_SPECS (no financials)
- Rebalance + label horizon: 20 trading days
- Train readiness: MIN_TRAIN_SAMPLES=1500, MIN_TRAIN_REBALANCES=100
- Output: data/trend_xs_xgb_results_20d/ (does not wipe legacy 5d results)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
sys.path.insert(0, str(BASE))

from strategies.trend_xs_multifactor import (  # noqa: E402
    CAPITAL,
    COMMISSION_RATE,
    COMMODITY_SPECS,
    ENTRY_WINDOW,
    FACTOR_COLS,
    ATR_WINDOW,
    MAX_LOTS_PER_NAME,
    MIN_HISTORY,
    RISK_FRAC_PER_NAME,
    SELECT_PCT,
    atr_lots,
    compute_features,
    select_names,
)
from strategies.trend_xs_xgb import (  # noqa: E402
    HORIZON_DAYS,
    MIN_TRAIN_REBALANCES,
    MIN_TRAIN_SAMPLES,
    REBALANCE_EVERY_N_DAYS_XGB,
    XGB_FEATURE_COLS,
    XGB_PARAMS,
    ExpandingXGBScorer,
    add_xgb_extras,
)

# Local aliases for this retune run
REBALANCE_EVERY_N_DAYS = REBALANCE_EVERY_N_DAYS_XGB  # 20

DATA_DIR = BASE / "data"
OUT_DIR = DATA_DIR / "trend_xs_xgb_results_20d"
PRIOR_XGB_SUMMARY = DATA_DIR / "trend_xs_xgb_results" / "summary.json"  # 12-name 5d
EW20_SUMMARY = DATA_DIR / "trend_xs_results_20" / "summary.json"  # equal-weight 20


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
    feat = add_xgb_extras(compute_features(df))
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
    score_mode_log = []

    last_close = {s: np.nan for s in symbols}
    cum_realized = 0.0
    rebalance_countdown = 0

    scorer = ExpandingXGBScorer(
        min_train_samples=MIN_TRAIN_SAMPLES,
        min_train_rebalances=MIN_TRAIN_REBALANCES,
        horizon=HORIZON_DAYS,
        params=XGB_PARAMS,
    )

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

    for i in range(start_i, len(calendar)):
        dt = calendar[i]

        for s in symbols:
            if dt in frames[s].index:
                last_close[s] = float(frames[s].loc[dt, "close"])

        scorer.label_past(frames, dt)

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
                rec = {
                    "symbol": s,
                    "close": float(r["close"]),
                    "atr": float(r["atr"]),
                    "size": float(r["size"]),
                    "pricetick": float(r["pricetick"]),
                    "long_eligible": bool(r["long_eligible"]) if pd.notna(r["long_eligible"]) else False,
                    "short_eligible": bool(r["short_eligible"]) if pd.notna(r["short_eligible"]) else False,
                }
                for c in XGB_FEATURE_COLS:
                    rec[c] = float(r[c]) if c in r.index and pd.notna(r[c]) else np.nan
                records.append(rec)

            if records:
                snap = pd.DataFrame(records).set_index("symbol")

                used_ml = scorer.fit_if_ready(asof=dt)

                long_pool = snap[snap["long_eligible"]]
                short_pool = snap[snap["short_eligible"]]

                long_scores, mode_l = (
                    scorer.score_pool(long_pool) if len(long_pool) else (pd.Series(dtype=float), "fallback")
                )
                short_scores, mode_s = (
                    scorer.score_pool(short_pool) if len(short_pool) else (pd.Series(dtype=float), "fallback")
                )
                mode = mode_l if len(long_pool) else mode_s
                if len(long_pool) and len(short_pool):
                    mode = "xgb" if (mode_l == "xgb" or mode_s == "xgb") else "fallback"
                score_mode_log.append({"date": str(dt.date()), "mode": mode, "used_ml_fit": used_ml})

                long_sel = select_names(long_scores, "long", SELECT_PCT)
                short_sel = select_names(short_scores, "short", SELECT_PCT)
                both = set(long_sel) & set(short_sel)
                long_sel = [x for x in long_sel if x not in both]
                short_sel = [x for x in short_sel if x not in both]

                target: dict[str, int] = {}
                n_sel = len(long_sel) + len(short_sel)
                for s in long_sel:
                    lots = atr_lots(CAPITAL, snap.loc[s, "atr"], snap.loc[s, "size"], n_sel)
                    if lots > 0:
                        target[s] = lots
                for s in short_sel:
                    lots = atr_lots(CAPITAL, snap.loc[s, "atr"], snap.loc[s, "size"], n_sel)
                    if lots > 0:
                        target[s] = -lots

                for sym in list(positions.keys()):
                    want = target.get(sym, 0)
                    cur = positions[sym]["dir"] * positions[sym]["lots"]
                    if want == 0 or np.sign(want) != np.sign(cur) or abs(want) != abs(cur):
                        if dt in frames[sym].index:
                            px = float(frames[sym].loc[dt, "close"])
                        else:
                            px = last_close[sym]
                        close_position(sym, dt, px, "rebalance_close")

                for sym, signed_lots in target.items():
                    if sym in positions:
                        continue
                    direction = 1 if signed_lots > 0 else -1
                    lots = abs(signed_lots)
                    px = float(snap.loc[sym, "close"])
                    open_position(
                        sym,
                        dt,
                        direction,
                        lots,
                        px,
                        float(snap.loc[sym, "size"]),
                        float(snap.loc[sym, "pricetick"]),
                        "rebalance_open",
                    )

                scorer.record_features(dt, snap)

        rebalance_countdown -= 1

        mtm = mark_mtm(dt)
        equity = CAPITAL + cum_realized + mtm
        n_long = sum(1 for p in positions.values() if p["dir"] > 0)
        n_short = sum(1 for p in positions.values() if p["dir"] < 0)
        equity_rows.append(
            {
                "datetime": dt,
                "equity": equity,
                "realized": cum_realized,
                "mtm": mtm,
                "n_long": n_long,
                "n_short": n_short,
                "n_pos": len(positions),
            }
        )

    eq = pd.DataFrame(equity_rows).set_index("datetime")
    trades = pd.DataFrame(trade_rows)

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
    close_pnls = trades.loc[trades["action"] == "CLOSE", "pnl"] if not trades.empty else pd.Series(dtype=float)
    win_rate = float((close_pnls > 0).mean() * 100.0) if len(close_pnls) else None

    n_xgb_days = sum(1 for r in score_mode_log if r["mode"] == "xgb")
    n_fb_days = sum(1 for r in score_mode_log if r["mode"] == "fallback")

    return {
        "equity": eq,
        "trades": trades,
        "rebalance_dates": rebalance_dates,
        "score_mode_log": score_mode_log,
        "scorer_stats": scorer.stats(),
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
        "n_xgb_rebals": n_xgb_days,
        "n_fallback_rebals": n_fb_days,
        "params": {
            "entry_window": ENTRY_WINDOW,
            "atr_window": ATR_WINDOW,
            "select_pct": SELECT_PCT,
            "rebalance_every_n_days": REBALANCE_EVERY_N_DAYS,
            "capital": CAPITAL,
            "commission_rate": COMMISSION_RATE,
            "risk_frac_per_name": RISK_FRAC_PER_NAME,
            "max_lots_per_name": MAX_LOTS_PER_NAME,
            "factor_cols_baseline": list(FACTOR_COLS),
            "xgb_feature_cols": list(XGB_FEATURE_COLS),
            "horizon_days": HORIZON_DAYS,
            "min_train_samples": MIN_TRAIN_SAMPLES,
            "min_train_rebalances": MIN_TRAIN_REBALANCES,
            "xgb_params": dict(XGB_PARAMS),
            "label": "forward close-to-close return over HORIZON_DAYS (regression); rank by prediction in pool",
            "train_scheme": "expanding walk-forward; train on labeled rows with date < t; fallback until min samples",
            "retune_note": "20 commodities, 20d rebalance/label, MIN_TRAIN_SAMPLES=1500, MIN_TRAIN_REBALANCES=100",
        },
    }


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> None:
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
    print(
        f"Retune: rebalance={REBALANCE_EVERY_N_DAYS}d label={HORIZON_DAYS}d "
        f"min_samples={MIN_TRAIN_SAMPLES} min_rebals={MIN_TRAIN_REBALANCES}"
    )
    print("Running walk-forward XGB backtest (may take several minutes)...")
    result = run_backtest(frames)
    if result.get("error"):
        raise SystemExit(result["error"])

    eq: pd.DataFrame = result["equity"]
    trades: pd.DataFrame = result["trades"]

    equity_path = OUT_DIR / "equity_curve.csv"
    eq.to_csv(equity_path, encoding="utf-8-sig")
    trades_path = OUT_DIR / "trades.csv"
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")

    mode_path = OUT_DIR / "score_mode_log.csv"
    pd.DataFrame(result["score_mode_log"]).to_csv(mode_path, index=False, encoding="utf-8-sig")

    prior_xgb = _load_json(PRIOR_XGB_SUMMARY)
    ew20 = _load_json(EW20_SUMMARY)

    summary = {
        "strategy": "趋势门控 + 截面XGBoost多因子 (20d retune)",
        "strategy_en": "Trend-gated XS multifactor with XGBoost scoring (20d retune)",
        "universe": result["symbols"],
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
        "n_xgb_rebals": result["n_xgb_rebals"],
        "n_fallback_rebals": result["n_fallback_rebals"],
        "scorer_stats": result["scorer_stats"],
        "params": result["params"],
        "compare_prior_xgb_12name_5d": (
            {
                "total_return_pct": prior_xgb.get("total_return_pct"),
                "annual_return_pct": prior_xgb.get("annual_return_pct"),
                "max_ddpercent": prior_xgb.get("max_ddpercent"),
                "sharpe_ratio": prior_xgb.get("sharpe_ratio"),
                "end_equity": prior_xgb.get("end_equity"),
                "win_rate_pct": prior_xgb.get("win_rate_pct"),
                "n_xgb_rebals": prior_xgb.get("n_xgb_rebals"),
                "n_fallback_rebals": prior_xgb.get("n_fallback_rebals"),
                "universe_size": len(prior_xgb.get("universe") or []),
                "source": str(PRIOR_XGB_SUMMARY),
            }
            if prior_xgb
            else None
        ),
        "compare_equal_weight_20": (
            {
                "total_return_pct": ew20.get("total_return_pct"),
                "annual_return_pct": ew20.get("annual_return_pct"),
                "max_ddpercent": ew20.get("max_ddpercent"),
                "sharpe_ratio": ew20.get("sharpe_ratio"),
                "end_equity": ew20.get("end_equity"),
                "win_rate_pct": ew20.get("win_rate_pct"),
                "universe_size": len(ew20.get("universe") or []),
                "source": str(EW20_SUMMARY),
            }
            if ew20
            else None
        ),
        "equity_csv": str(equity_path),
        "trades_csv": str(trades_path),
        "score_mode_csv": str(mode_path),
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "Trend-gated XS multifactor + XGBoost backtest (20d retune)",
        f"universe ({len(result['symbols'])}): {', '.join(result['symbols'])}",
        f"range: {result['start']} -> {result['end']}  days={result['days']}",
        f"rebalance: every {REBALANCE_EVERY_N_DAYS} trading days | select_pct={SELECT_PCT}",
        f"label: forward {HORIZON_DAYS}d return (regression) | train: expanding walk-forward",
        f"min_train_samples={MIN_TRAIN_SAMPLES} min_train_rebals={MIN_TRAIN_REBALANCES}",
        f"features: {', '.join(XGB_FEATURE_COLS)}",
        f"xgb_params: depth={XGB_PARAMS['max_depth']} n_estimators={XGB_PARAMS['n_estimators']} lr={XGB_PARAMS['learning_rate']}",
        f"capital={CAPITAL} | commission={COMMISSION_RATE} | slippage=1 tick | risk_frac/name={RISK_FRAC_PER_NAME}",
        "",
        f"total_return: {result['total_return_pct']:.4f}%",
        f"annual_return: {result['annual_return_pct']:.4f}%",
        f"max_drawdown: {result['max_ddpercent']:.4f}%",
        f"Sharpe: {result['sharpe_ratio']:.4f}",
        f"end_equity: {result['end_equity']:.2f}  net_pnl: {result['total_net_pnl']:.2f}",
        f"opens: {result['n_opens']}  closes: {result['n_closes']}  win_rate(closes): {result['win_rate_pct']}%",
        f"rebalances: {len(result['rebalance_dates'])}  (xgb={result['n_xgb_rebals']}, fallback={result['n_fallback_rebals']})",
        "",
    ]
    if prior_xgb:
        lines += [
            "Compare vs prior XGB (12-name, 5d horizon/rebal, min_samples=200):",
            (
                f"  prior   total={prior_xgb.get('total_return_pct')}%  ann={prior_xgb.get('annual_return_pct')}%  "
                f"maxDD={prior_xgb.get('max_ddpercent')}%  Sharpe={prior_xgb.get('sharpe_ratio')}  "
                f"xgb/fb={prior_xgb.get('n_xgb_rebals')}/{prior_xgb.get('n_fallback_rebals')}"
            ),
            (
                f"  this    total={result['total_return_pct']}%  ann={result['annual_return_pct']}%  "
                f"maxDD={result['max_ddpercent']}%  Sharpe={result['sharpe_ratio']}  "
                f"xgb/fb={result['n_xgb_rebals']}/{result['n_fallback_rebals']}"
            ),
            "",
        ]
    if ew20:
        lines += [
            "Compare vs equal-weight 20-name baseline (5d rebal, no XGB):",
            (
                f"  ew20    total={ew20.get('total_return_pct')}%  ann={ew20.get('annual_return_pct')}%  "
                f"maxDD={ew20.get('max_ddpercent')}%  Sharpe={ew20.get('sharpe_ratio')}"
            ),
            (
                f"  xgb20d  total={result['total_return_pct']}%  ann={result['annual_return_pct']}%  "
                f"maxDD={result['max_ddpercent']}%  Sharpe={result['sharpe_ratio']}"
            ),
            "",
        ]
    imp = result["scorer_stats"].get("feature_importance") or {}
    if imp:
        lines.append("Final-model feature importance (gain-style, last fit):")
        for k, v in sorted(imp.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {k}: {v:.4f}")
        lines.append("")
    lines += [
        "Caveats:",
        "- Sina main-force continuous bars; rolls/gaps not modeled.",
        "- Fill at signal-bar close; optimistic vs next-open fills.",
        "- Early period uses equal-weight fallback until train thresholds met.",
        "- Higher readiness delays ML start; curve is hybrid (EW then XGB).",
        "- EW20 baseline still uses 5d rebalance — horizon differs from this 20d run.",
        "- Past backtest != future expectation.",
    ]
    report_path = OUT_DIR / "report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSummary: {summary_path}")
    print(f"Report: {report_path}")
    print(f"Equity: {equity_path}")
    print(f"Trades: {trades_path}")


if __name__ == "__main__":
    main()
