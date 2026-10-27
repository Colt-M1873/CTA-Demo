# -*- coding: utf-8 -*-
"""Modest signal-param grid for trend_xs_adx_risk (Donchian/XS/filter), risk fixed at search_best.

Writes:
  data/trend_xs_signal_search/search_summary.csv
  data/trend_xs_signal_search/best_config.json
  data/trend_xs_signal_search_best_results/  (full artifacts for winner)
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
sys.path.insert(0, str(BASE))

import strategies.trend_xs_adx as adx_mod
import strategies.trend_xs_adx_risk as risk_mod
import backtest_trend_xs_adx_risk as bt

from strategies.trend_xs_adx import (
    COMMODITY_SPECS,
    DEFAULT_FACTOR_COLS,
    MIN_HISTORY,
    apply_signal_config,
)
from strategies.trend_xs_adx_risk import apply_risk_profile

DATA_DIR = BASE / "data"
OUT_DIR = DATA_DIR / "trend_xs_signal_search"
PRIOR_RISK_BEST = DATA_DIR / "trend_xs_adx_risk_search_best_results" / "summary.json"
PRIOR_ADX = DATA_DIR / "trend_xs_adx_results" / "summary.json"

ALL_FACTORS = list(DEFAULT_FACTOR_COLS)
NO_ADX = [c for c in ALL_FACTORS if c != "adx"]
NO_OI = [c for c in ALL_FACTORS if c != "oi_chg_20"]
MOM_LOWVOL = ["mom_20", "mom_60", "mom_120", "low_vol"]


def load_raw(name: str, spec: dict) -> pd.DataFrame | None:
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
    out = df.copy()
    out["size"] = spec["size"]
    out["pricetick"] = spec["pricetick"]
    out["symbol"] = name
    return out


def feature_cache_key(cfg: dict) -> tuple:
    return (
        int(cfg["entry_window"]),
        float(cfg["body_atr_min"]),
        bool(cfg["use_volume_filter"]),
    )


def build_featured(raw_frames: dict[str, pd.DataFrame], cfg: dict) -> dict[str, pd.DataFrame]:
    apply_signal_config(
        {
            "entry_window": cfg["entry_window"],
            "select_pct": cfg["select_pct"],
            "rebalance_every_n_days": cfg["rebalance_every_n_days"],
            "body_atr_min": cfg["body_atr_min"],
            "use_volume_filter": cfg["use_volume_filter"],
            "factor_cols": cfg["factor_cols"],
        },
        profile_name=cfg["name"],
    )
    frames: dict[str, pd.DataFrame] = {}
    for name, raw in raw_frames.items():
        feat = adx_mod.compute_features(raw)
        feat["size"] = raw["size"]
        feat["pricetick"] = raw["pricetick"]
        feat["symbol"] = name
        frames[name] = feat
    return frames


def sync_signal_bindings(cfg: dict) -> None:
    """Patch adx / risk / backtest module bindings used at runtime."""
    apply_signal_config(
        {
            "entry_window": cfg["entry_window"],
            "select_pct": cfg["select_pct"],
            "rebalance_every_n_days": cfg["rebalance_every_n_days"],
            "body_atr_min": cfg["body_atr_min"],
            "use_volume_filter": cfg["use_volume_filter"],
            "factor_cols": cfg["factor_cols"],
        },
        profile_name=cfg["name"],
    )
    for mod in (adx_mod, risk_mod, bt):
        mod.ENTRY_WINDOW = int(cfg["entry_window"])
        mod.SELECT_PCT = float(cfg["select_pct"])
        mod.REBALANCE_EVERY_N_DAYS = int(cfg["rebalance_every_n_days"])
        mod.BODY_ATR_MIN = float(cfg["body_atr_min"])
        mod.FACTOR_COLS = list(cfg["factor_cols"])
        if hasattr(mod, "USE_VOLUME_FILTER"):
            mod.USE_VOLUME_FILTER = bool(cfg["use_volume_filter"])


def build_grid() -> list[dict]:
    configs: list[dict] = []

    def add(name: str, **kw):
        cfg = {
            "entry_window": 20,
            "select_pct": 0.25,
            "rebalance_every_n_days": 5,
            "body_atr_min": 0.25,
            "use_volume_filter": True,
            "factor_cols": list(ALL_FACTORS),
            "factor_set": "all",
        }
        cfg.update(kw)
        cols = list(cfg["factor_cols"])
        if cols == ALL_FACTORS:
            cfg["factor_set"] = "all"
        elif cols == NO_ADX:
            cfg["factor_set"] = "no_adx"
        elif cols == NO_OI:
            cfg["factor_set"] = "no_oi"
        elif cols == MOM_LOWVOL:
            cfg["factor_set"] = "mom_lowvol"
        elif "factor_set" not in kw:
            cfg["factor_set"] = "custom"
        cfg["name"] = name
        cfg["factor_cols"] = cols
        configs.append(cfg)

    add("baseline")
    add("entry_15", entry_window=15)
    add("entry_30", entry_window=30)
    add("entry_40", entry_window=40)
    add("entry_55", entry_window=55)
    add("select_15", select_pct=0.15)
    add("select_35", select_pct=0.35)
    add("rebal_10", rebalance_every_n_days=10)
    add("rebal_20", rebalance_every_n_days=20)
    add("body_015", body_atr_min=0.15)
    add("body_04", body_atr_min=0.40)
    add("vol_off", use_volume_filter=False)
    add("body_015_vol_off", body_atr_min=0.15, use_volume_filter=False)
    add("no_adx", factor_cols=list(NO_ADX))
    add("no_oi", factor_cols=list(NO_OI))
    add("mom_lowvol", factor_cols=list(MOM_LOWVOL))
    add("entry_40_select_15", entry_window=40, select_pct=0.15)
    add("entry_40_rebal_10", entry_window=40, rebalance_every_n_days=10)
    add("entry_30_select_35_rebal_10", entry_window=30, select_pct=0.35, rebalance_every_n_days=10)
    add("entry_55_body_04", entry_window=55, body_atr_min=0.40)
    add("entry_15_select_35", entry_window=15, select_pct=0.35)
    add("entry_30_vol_off", entry_window=30, use_volume_filter=False)
    add("select_15_rebal_20", select_pct=0.15, rebalance_every_n_days=20)
    add("entry_40_no_adx", entry_window=40, factor_cols=list(NO_ADX))
    add("entry_20_rebal_10_body_015", entry_window=20, rebalance_every_n_days=10, body_atr_min=0.15)
    return configs


def save_full_results(name: str, result: dict, cfg: dict, risk_profile: str) -> Path:
    out = DATA_DIR / f"trend_xs_signal_{name}_results"
    out.mkdir(parents=True, exist_ok=True)
    result["equity"].to_csv(out / "equity_curve.csv", encoding="utf-8-sig")
    result["trades"].to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    result["risk_log"].to_csv(out / "risk_rebalance_log.csv", index=False, encoding="utf-8-sig")

    prior_risk = None
    if PRIOR_RISK_BEST.exists():
        prior_risk = json.loads(PRIOR_RISK_BEST.read_text(encoding="utf-8"))
    prior_adx = None
    if PRIOR_ADX.exists():
        prior_adx = json.loads(PRIOR_ADX.read_text(encoding="utf-8"))

    summary = {
        "strategy": "趋势门控+假突破过滤+截面等权(+可选ADX)+等权底仓+search_best风控；信号参数搜索优胜",
        "strategy_en": "Trend-gated XS EW + fake-breakout + search_best risk; signal-param search winner",
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
        "flat_force_closes": result["flat_force_closes"],
        "days_half": result["days_half"],
        "days_flat": result["days_flat"],
        "avg_gross_leverage": result["avg_gross_leverage"],
        "max_gross_leverage": result["max_gross_leverage"],
        "params": result["params"],
        "signal_profile": name,
        "risk_profile": risk_profile,
        "search_config": {k: (list(v) if k == "factor_cols" else v) for k, v in cfg.items()},
        "prior_search_best_risk": {
            "total_return_pct": None if not prior_risk else prior_risk.get("total_return_pct"),
            "sharpe_ratio": None if not prior_risk else prior_risk.get("sharpe_ratio"),
            "max_ddpercent": None if not prior_risk else prior_risk.get("max_ddpercent"),
            "annual_return_pct": None if not prior_risk else prior_risk.get("annual_return_pct"),
        },
        "prior_adx_40": {
            "total_return_pct": None if not prior_adx else prior_adx.get("total_return_pct"),
            "sharpe_ratio": None if not prior_adx else prior_adx.get("sharpe_ratio"),
            "max_ddpercent": None if not prior_adx else prior_adx.get("max_ddpercent"),
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    report = [
        f"Trend XS signal search winner: {name}",
        f"Sharpe={result['sharpe_ratio']}  ann={result['annual_return_pct']}%  "
        f"DD={result['max_ddpercent']}%  total={result['total_return_pct']}%",
        f"signal: entry={cfg['entry_window']} select={cfg['select_pct']} "
        f"rebal={cfg['rebalance_every_n_days']} bodyATR={cfg['body_atr_min']} "
        f"vol_filter={cfg['use_volume_filter']} factors={cfg.get('factor_set')}",
        f"risk profile fixed: {risk_profile}",
        f"avg/max gross={result['avg_gross_leverage']}/{result['max_gross_leverage']}",
        "",
        "Note: signal-only tuning on same scheme; in-sample Sharpe still typically ~0.1-0.25, not 0.6.",
    ]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return out


def pin_signal_best_in_module(cfg: dict) -> None:
    path = BASE / "strategies" / "trend_xs_adx.py"
    text = path.read_text(encoding="utf-8")
    block = (
        "SIGNAL_PROFILES = {\n"
        '    "baseline": {\n'
        '        "entry_window": 20,\n'
        '        "select_pct": 0.25,\n'
        '        "rebalance_every_n_days": 5,\n'
        '        "body_atr_min": 0.25,\n'
        '        "use_volume_filter": True,\n'
        '        "factor_cols": list(DEFAULT_FACTOR_COLS),\n'
        "    },\n"
        '    "signal_best": {\n'
        f'        "entry_window": {int(cfg["entry_window"])},\n'
        f'        "select_pct": {float(cfg["select_pct"])},\n'
        f'        "rebalance_every_n_days": {int(cfg["rebalance_every_n_days"])},\n'
        f'        "body_atr_min": {float(cfg["body_atr_min"])},\n'
        f'        "use_volume_filter": {bool(cfg["use_volume_filter"])},\n'
        f'        "factor_cols": {repr(list(cfg["factor_cols"]))},\n'
        "    },\n"
        "}\n"
    )
    pat = re.compile(r"SIGNAL_PROFILES = \{.*?\}\n_ACTIVE_SIGNAL_PROFILE", re.S)
    new_text, n = pat.subn(block + "_ACTIVE_SIGNAL_PROFILE", text, count=1)
    if n != 1:
        raise RuntimeError(f"Failed to rewrite SIGNAL_PROFILES (n={n})")
    path.write_text(new_text, encoding="utf-8")


def patch_backtest_cli_for_signal_profile() -> None:
    path = BASE / "backtest_trend_xs_adx_risk.py"
    text = path.read_text(encoding="utf-8")
    if "--signal-profile" in text:
        return
    if "apply_signal_profile" not in text:
        text = text.replace(
            "    apply_risk_profile,\n",
            "    apply_risk_profile,\n    apply_signal_profile,\n    SIGNAL_PROFILES,\n",
            1,
        )
    text = text.replace(
        'def main(profile: str = "tight") -> None:',
        'def main(profile: str = "tight", signal_profile: str | None = None) -> None:',
        1,
    )
    text = text.replace(
        "    apply_risk_profile(profile)\n",
        "    apply_risk_profile(profile)\n"
        "    if signal_profile:\n"
        "        sp = apply_signal_profile(signal_profile)\n"
        "        global ENTRY_WINDOW, SELECT_PCT, REBALANCE_EVERY_N_DAYS, BODY_ATR_MIN, FACTOR_COLS\n"
        '        ENTRY_WINDOW = int(sp["entry_window"])\n'
        '        SELECT_PCT = float(sp["select_pct"])\n'
        '        REBALANCE_EVERY_N_DAYS = int(sp["rebalance_every_n_days"])\n'
        '        BODY_ATR_MIN = float(sp["body_atr_min"])\n'
        '        FACTOR_COLS = list(sp["factor_cols"])\n'
        '        if hasattr(risk_mod, "USE_VOLUME_FILTER"):\n'
        '            risk_mod.USE_VOLUME_FILTER = bool(sp["use_volume_filter"])\n'
        "        import strategies.trend_xs_adx as _adx\n"
        '        _adx.USE_VOLUME_FILTER = bool(sp["use_volume_filter"])\n'
        '        print(f"Signal profile: {signal_profile} -> {sp}")\n',
        1,
    )
    text = text.replace(
        '    OUT_DIR = OUT_DIR_BY_PROFILE.get(profile, DATA_DIR / f"trend_xs_adx_risk_{profile}_results")\n',
        "    if signal_profile:\n"
        '        OUT_DIR = DATA_DIR / f"trend_xs_signal_{signal_profile}_results"\n'
        "    else:\n"
        '        OUT_DIR = OUT_DIR_BY_PROFILE.get(profile, DATA_DIR / f"trend_xs_adx_risk_{profile}_results")\n',
        1,
    )
    text = text.replace(
        "    args = ap.parse_args()\n    main(profile=args.profile)\n",
        "    ap.add_argument(\n"
        '        "--signal-profile",\n'
        "        default=None,\n"
        '        help="Optional signal profile (e.g. baseline, signal_best)",\n'
        "    )\n"
        "    args = ap.parse_args()\n"
        "    main(profile=args.profile, signal_profile=args.signal_profile)\n",
        1,
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading raw universe...")
    raw_frames: dict[str, pd.DataFrame] = {}
    for name, spec in COMMODITY_SPECS.items():
        f = load_raw(name, spec)
        if f is not None:
            raw_frames[name] = f
            print(f"  {name}: {len(f)}")
    if len(raw_frames) < 4:
        raise SystemExit(f"Need >=4 symbols, got {len(raw_frames)}")
    print(f"Universe n={len(raw_frames)}")

    risk_profile = "search_best"
    apply_risk_profile(risk_profile)
    print(f"Risk profile fixed: {risk_profile}")

    grid = build_grid()
    print(f"Signal grid size={len(grid)}")

    feat_cache: dict[tuple, dict[str, pd.DataFrame]] = {}
    rows = []
    t0 = time.time()

    for i, cfg in enumerate(grid, 1):
        name = cfg["name"]
        key = feature_cache_key(cfg)
        if key not in feat_cache:
            print(f"  building features for key={key} ...", flush=True)
            feat_cache[key] = build_featured(raw_frames, cfg)
        frames = feat_cache[key]
        sync_signal_bindings(cfg)
        apply_risk_profile(risk_profile)
        t1 = time.time()
        print(f"[{i}/{len(grid)}] {name} ...", flush=True)
        result = bt.run_backtest(frames)
        elapsed = time.time() - t1
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
            rows.append(
                {
                    "name": name,
                    "error": result["error"],
                    **{k: v for k, v in cfg.items() if k != "factor_cols"},
                    "factor_cols": "|".join(cfg["factor_cols"]),
                }
            )
            continue
        row = {
            "name": name,
            "sharpe_ratio": result["sharpe_ratio"],
            "annual_return_pct": result["annual_return_pct"],
            "total_return_pct": result["total_return_pct"],
            "max_ddpercent": result["max_ddpercent"],
            "avg_gross_leverage": result["avg_gross_leverage"],
            "max_gross_leverage": result["max_gross_leverage"],
            "days_half": result["days_half"],
            "days_flat": result["days_flat"],
            "n_opens": result["n_opens"],
            "win_rate_pct": result["win_rate_pct"],
            "end_equity": result["end_equity"],
            "filter_reject_count": result["filter_reject_count"],
            "elapsed_sec": round(elapsed, 1),
            "entry_window": cfg["entry_window"],
            "select_pct": cfg["select_pct"],
            "rebalance_every_n_days": cfg["rebalance_every_n_days"],
            "body_atr_min": cfg["body_atr_min"],
            "use_volume_filter": cfg["use_volume_filter"],
            "factor_set": cfg["factor_set"],
            "factor_cols": "|".join(cfg["factor_cols"]),
            "risk_profile": risk_profile,
        }
        rows.append(row)
        print(
            f"  Sharpe={result['sharpe_ratio']:.4f}  "
            f"ann={result['annual_return_pct']:.3f}%  "
            f"DD={result['max_ddpercent']:.2f}%  "
            f"total={result['total_return_pct']:.2f}%  "
            f"({elapsed:.0f}s)",
            flush=True,
        )

    df = pd.DataFrame(rows)
    if "sharpe_ratio" in df.columns:
        df = df.sort_values(
            by=["sharpe_ratio", "max_ddpercent", "total_return_pct"],
            ascending=[False, False, False],
            na_position="last",
        )
    csv_path = OUT_DIR / "search_summary.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\nWrote {csv_path}")
    print(f"Total elapsed {time.time() - t0:.0f}s")

    ok = df[df["sharpe_ratio"].notna()].copy() if "sharpe_ratio" in df.columns else df
    best = ok.iloc[0].to_dict()
    rec_name = str(best["name"])
    rec_cfg = next(c for c in grid if c["name"] == rec_name)

    best_path = OUT_DIR / "best_config.json"
    best_payload = {
        "recommended_name": rec_name,
        "registered_as": "signal_best",
        "risk_profile": risk_profile,
        "config": {
            "entry_window": rec_cfg["entry_window"],
            "select_pct": rec_cfg["select_pct"],
            "rebalance_every_n_days": rec_cfg["rebalance_every_n_days"],
            "body_atr_min": rec_cfg["body_atr_min"],
            "use_volume_filter": rec_cfg["use_volume_filter"],
            "factor_cols": list(rec_cfg["factor_cols"]),
            "factor_set": rec_cfg["factor_set"],
        },
        "metrics": {
            k: best.get(k)
            for k in (
                "sharpe_ratio",
                "annual_return_pct",
                "total_return_pct",
                "max_ddpercent",
                "avg_gross_leverage",
                "max_gross_leverage",
                "days_half",
                "days_flat",
                "n_opens",
                "win_rate_pct",
                "end_equity",
            )
        },
        "note": (
            "Primary sort: Sharpe, then max DD (less negative), then total return. "
            "Risk fixed at search_best. Signal-only grid; do not expect Sharpe ~0.6."
        ),
    }
    best_path.write_text(json.dumps(best_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nRe-running winner {rec_name} as signal_best...")
    key = feature_cache_key(rec_cfg)
    frames = feat_cache[key]
    sync_signal_bindings({**rec_cfg, "name": "signal_best"})
    apply_risk_profile(risk_profile)
    result = bt.run_backtest(frames)
    out_dir = save_full_results("signal_best", result, rec_cfg, risk_profile)
    alias = save_full_results(rec_name, result, rec_cfg, risk_profile)

    pin_signal_best_in_module(rec_cfg)
    patch_backtest_cli_for_signal_profile()

    try:
        md_table = ok.head(8)[
            [
                "name",
                "sharpe_ratio",
                "annual_return_pct",
                "max_ddpercent",
                "total_return_pct",
                "entry_window",
                "select_pct",
                "rebalance_every_n_days",
                "body_atr_min",
                "use_volume_filter",
                "factor_set",
            ]
        ].to_markdown(index=False)
    except Exception:
        md_table = ok.head(8).to_string(index=False)

    docs = BASE / "docs" / "trend_gated_xs_signal_search.md"
    lines = [
        "# Signal-param search (risk fixed: search_best)",
        "",
        f"Grid size: {len(grid)}. Sort: Sharpe → max DD (less neg) → total return.",
        f"Winner: **{rec_name}** registered as `signal_best`.",
        "",
        "## Winner",
        f"- Sharpe={best.get('sharpe_ratio')}  ann={best.get('annual_return_pct')}%  "
        f"DD={best.get('max_ddpercent')}%  total={best.get('total_return_pct')}%",
        f"- entry={rec_cfg['entry_window']} select={rec_cfg['select_pct']} "
        f"rebal={rec_cfg['rebalance_every_n_days']} bodyATR={rec_cfg['body_atr_min']} "
        f"vol_filter={rec_cfg['use_volume_filter']} factors={rec_cfg['factor_set']}",
        "",
        "## Top configs",
        "",
        md_table,
        "",
        "## Reproduce",
        "```",
        "python backtest_trend_xs_adx_risk.py --profile search_best --signal-profile signal_best",
        "python backtest_trend_xs_signal_search.py",
        "```",
        "",
        "## Ceiling note",
        "In-sample signal tuning on Sina main-force continuous + simplified costs typically "
        "keeps Sharpe in a low band (~0.1–0.3 here). Hitting 0.6+ needs cleaner data / richer "
        "factors / different scheme — not more Donchian/select knobs alone.",
        "",
        f"Artifacts: `{OUT_DIR}` ; best results: `{out_dir}`",
    ]
    docs.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Results: {out_dir}")
    print(f"Alias:   {alias}")
    print(f"Best config JSON: {best_path}")
    print(f"Doc: {docs}")
    print("\n=== TOP 8 ===")
    cols = [
        "name",
        "sharpe_ratio",
        "annual_return_pct",
        "max_ddpercent",
        "total_return_pct",
        "entry_window",
        "select_pct",
        "rebalance_every_n_days",
        "body_atr_min",
        "use_volume_filter",
        "factor_set",
    ]
    print(ok[cols].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
