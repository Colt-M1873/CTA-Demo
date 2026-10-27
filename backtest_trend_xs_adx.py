# -*- coding: utf-8 -*-
"""Backtest: Trend-gated XS + fake-breakout filter + EW sizing + ADX factor.

NO XGBoost. 40-commodity universe. Compare vs data/trend_xs_ew_filter_results/ (20-name EW+filter).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
sys.path.insert(0, str(BASE))

from strategies.trend_xs_adx import (  # noqa: E402
    ADX_WINDOW,
    BODY_ATR_MIN,
    CAPITAL,
    COMMISSION_RATE,
    COMMODITY_SPECS,
    ENTRY_WINDOW,
    FACTOR_COLS,
    GROSS_LEVERAGE,
    MAX_LOTS_PER_NAME,
    MIN_HISTORY,
    REBALANCE_EVERY_N_DAYS,
    SELECT_PCT,
    VOL_SMA_WINDOW,
    composite_scores,
    compute_features,
    equal_weight_lots,
    select_names,
)

DATA_DIR = BASE / "data"
OUT_DIR = DATA_DIR / "trend_xs_adx_results"
PRIOR_EW_FILTER_SUMMARY = DATA_DIR / "trend_xs_ew_filter_results" / "summary.json"
BASELINE_ATR_SUMMARY = DATA_DIR / "trend_xs_results_20" / "summary.json"


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

            if records:
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

                target: dict[str, int] = {}
                n_sel = len(long_sel) + len(short_sel)
                for s in long_sel:
                    lots = equal_weight_lots(
                        CAPITAL, snap.loc[s, "close"], snap.loc[s, "size"], n_sel
                    )
                    if lots > 0:
                        target[s] = lots
                for s in short_sel:
                    lots = equal_weight_lots(
                        CAPITAL, snap.loc[s, "close"], snap.loc[s, "size"], n_sel
                    )
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
    close_pnls = (
        trades.loc[trades["action"] == "CLOSE", "pnl"] if not trades.empty else pd.Series(dtype=float)
    )
    win_rate = float((close_pnls > 0).mean() * 100.0) if len(close_pnls) else None

    return {
        "equity": eq,
        "trades": trades,
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
        "params": {
            "entry_window": ENTRY_WINDOW,
            "adx_window": ADX_WINDOW,
            "select_pct": SELECT_PCT,
            "rebalance_every_n_days": REBALANCE_EVERY_N_DAYS,
            "capital": CAPITAL,
            "commission_rate": COMMISSION_RATE,
            "sizing": "equal_weight",
            "gross_leverage": GROSS_LEVERAGE,
            "max_lots_per_name": MAX_LOTS_PER_NAME,
            "body_atr_min": BODY_ATR_MIN,
            "vol_sma_window": VOL_SMA_WINDOW,
            "filter": "body_atr_and_volume_vs_prior_20d_sma",
            "factor_cols": list(FACTOR_COLS),
            "scoring": "equal_weight_robust_z; directional flipped for shorts; adx/low_vol positive both sides",
            "adx": "Wilder ADX(14) at signal-bar close (EOD-known)",
        },
    }


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
    result = run_backtest(frames)
    if result.get("error"):
        raise SystemExit(result["error"])

    eq: pd.DataFrame = result["equity"]
    trades: pd.DataFrame = result["trades"]

    equity_path = OUT_DIR / "equity_curve.csv"
    eq.to_csv(equity_path, encoding="utf-8-sig")
    trades_path = OUT_DIR / "trades.csv"
    trades.to_csv(trades_path, index=False, encoding="utf-8-sig")

    prior_ew = None
    if PRIOR_EW_FILTER_SUMMARY.exists():
        prior_ew = json.loads(PRIOR_EW_FILTER_SUMMARY.read_text(encoding="utf-8"))
    baseline_atr = None
    if BASELINE_ATR_SUMMARY.exists():
        baseline_atr = json.loads(BASELINE_ATR_SUMMARY.read_text(encoding="utf-8"))

    summary = {
        "strategy": "趋势门控 + 假突破过滤 + 截面等权因子(含ADX) + 等权仓位",
        "strategy_en": "Trend-gated XS EW factors incl. ADX + fake-breakout filter + equal-weight sizing",
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
        "params": result["params"],
        "prior_ew_filter_20": {
            "total_return_pct": prior_ew.get("total_return_pct") if prior_ew else None,
            "annual_return_pct": prior_ew.get("annual_return_pct") if prior_ew else None,
            "max_ddpercent": prior_ew.get("max_ddpercent") if prior_ew else None,
            "sharpe_ratio": prior_ew.get("sharpe_ratio") if prior_ew else None,
            "end_equity": prior_ew.get("end_equity") if prior_ew else None,
            "n_opens": prior_ew.get("n_opens") if prior_ew else None,
            "win_rate_pct": prior_ew.get("win_rate_pct") if prior_ew else None,
            "path": str(PRIOR_EW_FILTER_SUMMARY),
        },
        "baseline_atr_20": {
            "total_return_pct": baseline_atr.get("total_return_pct") if baseline_atr else None,
            "sharpe_ratio": baseline_atr.get("sharpe_ratio") if baseline_atr else None,
            "max_ddpercent": baseline_atr.get("max_ddpercent") if baseline_atr else None,
            "path": str(BASELINE_ATR_SUMMARY),
        },
        "equity_csv": str(equity_path),
        "trades_csv": str(trades_path),
    }
    summary_path = OUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "Trend-gated XS + fake-breakout filter + EW sizing + ADX(14) factor",
        f"universe ({len(result['symbols'])}): {', '.join(result['symbols'])}",
        f"range: {result['start']} -> {result['end']}  days={result['days']}",
        f"rebalance: every {REBALANCE_EVERY_N_DAYS} trading days | select_pct={SELECT_PCT}",
        f"capital={CAPITAL} | commission={COMMISSION_RATE} | slippage=1 tick",
        f"sizing=equal_weight gross_leverage={GROSS_LEVERAGE} max_lots={MAX_LOTS_PER_NAME}",
        f"filter: body/ATR>={BODY_ATR_MIN} AND volume>prior_{VOL_SMA_WINDOW}d_sma (plus Donchian gate)",
        f"factors: {', '.join(FACTOR_COLS)} (equal-weight robust-z; ADX Wilder {ADX_WINDOW} at close)",
        f"short scoring: directional factors flipped; ADX/low_vol stay positive",
        "",
        f"total_return: {result['total_return_pct']:.4f}%",
        f"annual_return: {result['annual_return_pct']:.4f}%",
        f"max_drawdown: {result['max_ddpercent']:.4f}%",
        f"Sharpe: {result['sharpe_ratio']:.4f}",
        f"end_equity: {result['end_equity']:.2f}  net_pnl: {result['total_net_pnl']:.2f}",
        f"opens: {result['n_opens']}  closes: {result['n_closes']}  win_rate(closes): {result['win_rate_pct']}%",
        f"rebalances: {len(result['rebalance_dates'])}",
        f"filter_rejects(gate_but_not_enter): {result['filter_reject_count']}",
        "",
    ]
    if prior_ew:
        lines += [
            "Compare vs prior EW+filter 20-name (trend_xs_ew_filter_results):",
            f"  prior total_return: {prior_ew.get('total_return_pct')}%  vs  {result['total_return_pct']}%",
            f"  prior annual: {prior_ew.get('annual_return_pct')}%  vs  {result['annual_return_pct']}%",
            f"  prior max_dd: {prior_ew.get('max_ddpercent')}%  vs  {result['max_ddpercent']}%",
            f"  prior Sharpe: {prior_ew.get('sharpe_ratio')}  vs  {result['sharpe_ratio']}",
            f"  prior opens: {prior_ew.get('n_opens')}  vs  {result['n_opens']}",
            "",
        ]
    lines += [
        "Caveats:",
        "- Sina main-force continuous; rolls/gaps not modeled.",
        "- Fill at signal-bar close; ADX_t known at that close.",
        "- Equal-weight may skip expensive contracts when budget < 1 lot.",
        "- New-name multipliers/priceticks are reasonable defaults — refine for live.",
        "- Universe 40 vs prior 20 — not a pure ADX-only A/B (both ADX and universe changed).",
        "- Past backtest != future expectation.",
    ]
    report_path = OUT_DIR / "report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSummary: {summary_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
