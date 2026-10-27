# -*- coding: utf-8 -*-
"""Grid search risk-overlay params for trend_xs_adx_risk (modest ~18 configs).

Loads commodity panel once, applies each risk config, runs walk-forward backtest
(no peek; same engine as backtest_trend_xs_adx_risk.py). Writes:
  data/trend_xs_adx_risk_search/search_summary.csv
  data/trend_xs_adx_risk_search/best_config.json
and re-runs the winner into data/trend_xs_adx_risk_<best>_results/
"""
from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
sys.path.insert(0, str(BASE))

import strategies.trend_xs_adx_risk as risk_mod
from strategies.trend_xs_adx_risk import (
    COMMODITY_SPECS,
    MIN_HISTORY,
    RISK_PROFILES,
    apply_risk_config,
    apply_risk_profile,
)
from backtest_trend_xs_adx_risk import load_symbol, run_backtest

DATA_DIR = BASE / "data"
OUT_DIR = DATA_DIR / "trend_xs_adx_risk_search"
PRIOR_ADX = DATA_DIR / "trend_xs_adx_results" / "summary.json"


def build_grid() -> list[dict]:
    """~18 named configs spanning vol / cap / DD / recovery / off switches."""
    configs: list[dict] = []

    def add(name: str, **kw):
        cfg = {
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
        }
        cfg.update(kw)
        cfg["name"] = name
        configs.append(cfg)

    # 0) Risk layer effectively off (matches ADX baseline path closely)
    add(
        "risk_off",
        enable_vol_target=False,
        enable_gross_leverage_cap=False,
        enable_dd_circuit=False,
        vol_target_annual=0.0,
        gross_leverage_cap=1.0,
        vol_scale_min=1.0,
    )

    # 1-3) Vol target only (no DD), different targets / floors
    add(
        "vol15_floor04_cap10_dd_off",
        vol_target_annual=0.15,
        vol_scale_min=0.40,
        gross_leverage_cap=1.0,
        enable_dd_circuit=False,
    )
    add(
        "vol20_floor04_cap10_dd_off",
        vol_target_annual=0.20,
        vol_scale_min=0.40,
        gross_leverage_cap=1.0,
        enable_dd_circuit=False,
    )
    add(
        "vol15_floor06_cap10_dd_off",
        vol_target_annual=0.15,
        vol_scale_min=0.60,
        gross_leverage_cap=1.0,
        enable_dd_circuit=False,
    )
    add(
        "vol20_floor06_cap10_dd_off",
        vol_target_annual=0.20,
        vol_scale_min=0.60,
        gross_leverage_cap=1.0,
        enable_dd_circuit=False,
    )

    # 4) Cap only + soft DD (no vol)
    add(
        "vol_off_cap08_dd15_25",
        enable_vol_target=False,
        gross_leverage_cap=0.80,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )
    add(
        "vol_off_cap10_dd20_30",
        enable_vol_target=False,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.20,
        dd_flat_threshold=0.30,
        dd_recovery_threshold=0.12,
        dd_flat_recover_threshold=0.20,
    )

    # 5-8) Combined: looser vol + softer DD
    add(
        "vol12_floor04_cap08_dd15_25",
        vol_target_annual=0.12,
        vol_scale_min=0.40,
        gross_leverage_cap=0.80,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )
    add(
        "vol15_floor04_cap08_dd15_25",
        vol_target_annual=0.15,
        vol_scale_min=0.40,
        gross_leverage_cap=0.80,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )
    add(
        "vol15_floor04_cap10_dd15_25",
        vol_target_annual=0.15,
        vol_scale_min=0.40,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )
    add(
        "vol20_floor05_cap10_dd20_30",
        vol_target_annual=0.20,
        vol_scale_min=0.50,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.20,
        dd_flat_threshold=0.30,
        dd_recovery_threshold=0.12,
        dd_flat_recover_threshold=0.20,
    )

    # 9-11) Higher floors (less aggressive vol scaling)
    add(
        "vol15_floor06_cap10_dd20_30",
        vol_target_annual=0.15,
        vol_scale_min=0.60,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.20,
        dd_flat_threshold=0.30,
        dd_recovery_threshold=0.12,
        dd_flat_recover_threshold=0.20,
    )
    add(
        "vol12_floor05_cap10_dd15_25",
        vol_target_annual=0.12,
        vol_scale_min=0.50,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )
    add(
        "vol10_floor04_cap07_dd15_25",
        vol_target_annual=0.10,
        vol_scale_min=0.40,
        gross_leverage_cap=0.70,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )

    # 12) DD half-only (flat practically off)
    add(
        "vol15_floor05_cap10_dd_half_only",
        vol_target_annual=0.15,
        vol_scale_min=0.50,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.99,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )

    # 13) Fast recovery hysteresis (recover sooner)
    add(
        "vol15_floor04_cap10_dd15_25_fast_rec",
        vol_target_annual=0.15,
        vol_scale_min=0.40,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.12,
        dd_flat_recover_threshold=0.18,
    )

    # 14) Slow recovery (more sticky)
    add(
        "vol15_floor04_cap10_dd15_25_slow_rec",
        vol_target_annual=0.15,
        vol_scale_min=0.40,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.05,
        dd_flat_recover_threshold=0.10,
    )

    # 15) Prior loose (reference inside search)
    add(
        "prior_loose",
        vol_target_annual=0.12,
        vol_scale_min=0.25,
        gross_leverage_cap=0.80,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )

    # 16) Soft vol target with high floor + no DD (near baseline with mild shrink)
    add(
        "vol20_floor08_cap10_dd_off",
        vol_target_annual=0.20,
        vol_scale_min=0.80,
        gross_leverage_cap=1.0,
        enable_dd_circuit=False,
    )

    # 17) Cap 1.0 + mild DD only
    add(
        "vol_off_cap10_dd15_25",
        enable_vol_target=False,
        gross_leverage_cap=1.0,
        dd_half_threshold=0.15,
        dd_flat_threshold=0.25,
        dd_recovery_threshold=0.10,
        dd_flat_recover_threshold=0.15,
    )

    return configs


def score_row(r: dict) -> tuple:
    """Primary Sharpe, then milder DD (less negative), then total return."""
    return (
        float(r.get("sharpe_ratio") or -999),
        float(r.get("max_ddpercent") or -999),
        float(r.get("total_return_pct") or -999),
    )


def save_full_results(name: str, result: dict, cfg: dict) -> Path:
    out = DATA_DIR / f"trend_xs_adx_risk_{name}_results"
    out.mkdir(parents=True, exist_ok=True)
    eq = result["equity"]
    trades = result["trades"]
    risk_log = result["risk_log"]
    eq.to_csv(out / "equity_curve.csv", encoding="utf-8-sig")
    trades.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    risk_log.to_csv(out / "risk_rebalance_log.csv", index=False, encoding="utf-8-sig")

    prior = None
    if PRIOR_ADX.exists():
        prior = json.loads(PRIOR_ADX.read_text(encoding="utf-8"))

    summary = {
        "strategy": "趋势门控+假突破过滤+截面等权(含ADX)+等权底仓+组合风控层",
        "strategy_en": "Trend-gated XS ADX EW + risk overlay (search best)",
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
        "risk_profile": name,
        "search_config": cfg,
        "prior_adx_40": {
            "total_return_pct": prior.get("total_return_pct") if prior else None,
            "sharpe_ratio": prior.get("sharpe_ratio") if prior else None,
            "max_ddpercent": prior.get("max_ddpercent") if prior else None,
            "annual_return_pct": prior.get("annual_return_pct") if prior else None,
        },
    }
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = [
        f"Trend XS ADX + RISK search winner: {name}",
        f"Sharpe={result['sharpe_ratio']}  ann={result['annual_return_pct']}%  "
        f"DD={result['max_ddpercent']}%  total={result['total_return_pct']}%",
        f"avg/max gross={result['avg_gross_leverage']}/{result['max_gross_leverage']}",
        f"HALF/FLAT days={result['days_half']}/{result['days_flat']}",
        f"config: {json.dumps(cfg, ensure_ascii=False)}",
        "",
        "Note: risk-only tuning; sample Sharpe still expected ~0.1-0.2, not 0.6.",
    ]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Loading universe...")
    frames: dict[str, pd.DataFrame] = {}
    for name, spec in COMMODITY_SPECS.items():
        f = load_symbol(name, spec)
        if f is not None:
            frames[name] = f
            print(f"  {name}: {len(f)}")
    if len(frames) < 4:
        raise SystemExit(f"Need >=4 symbols, got {len(frames)}")
    print(f"Universe n={len(frames)}")

    grid = build_grid()
    print(f"Grid size={len(grid)}")
    rows = []
    t0 = time.time()

    for i, cfg in enumerate(grid, 1):
        name = cfg["name"]
        payload = {k: v for k, v in cfg.items() if k != "name"}
        apply_risk_config(payload, profile_name=name)
        t1 = time.time()
        print(f"[{i}/{len(grid)}] {name} ...", flush=True)
        result = run_backtest(frames)
        elapsed = time.time() - t1
        if result.get("error"):
            print(f"  ERROR: {result['error']}")
            rows.append({"name": name, "error": result["error"], **payload})
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
            "elapsed_sec": round(elapsed, 1),
            **payload,
        }
        rows.append(row)
        print(
            f"  Sharpe={result['sharpe_ratio']:.4f}  "
            f"ann={result['annual_return_pct']:.3f}%  "
            f"DD={result['max_ddpercent']:.2f}%  "
            f"avg_gross={result['avg_gross_leverage']}  "
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

    # Pick best among risk-ON configs (exclude pure risk_off for 'recommended risk profile',
    # but still report it). Prefer best Sharpe overall for recommendation if it has risk on;
    # if risk_off wins, recommend best risk-on as practical risk overlay.
    ok = df[df["sharpe_ratio"].notna()].copy() if "sharpe_ratio" in df.columns else df
    best_overall = ok.iloc[0].to_dict() if len(ok) else None
    risk_on = ok[ok["name"] != "risk_off"] if len(ok) and "name" in ok.columns else ok
    best_risk_on = risk_on.iloc[0].to_dict() if len(risk_on) else best_overall

    # Recommended = best_risk_on (user asked to tune risk layer)
    recommend = best_risk_on
    rec_name = str(recommend["name"])
    rec_cfg = next(c for c in grid if c["name"] == rec_name)

    # Register as named profile "search_best" and re-run for full artifacts
    profile_body = {k: v for k, v in rec_cfg.items() if k != "name"}
    # store recovery rule text like others
    profile_body["dd_recovery_rule"] = (
        f"Escalate: DD>{profile_body['dd_half_threshold']:.0%}→HALF(0.5), "
        f"DD>{profile_body['dd_flat_threshold']:.0%}→FLAT(0). "
        f"Recover FLAT→HALF <= {profile_body['dd_flat_recover_threshold']:.0%}; "
        f"HALF→NORMAL <= {profile_body['dd_recovery_threshold']:.0%}."
    )
    RISK_PROFILES["search_best"] = deepcopy(profile_body)
    # Persist into module file is done separately; here write best_config.json
    best_path = OUT_DIR / "best_config.json"
    best_payload = {
        "recommended_name": rec_name,
        "registered_as": "search_best",
        "config": profile_body,
        "metrics": {
            k: recommend.get(k)
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
        "best_overall_name": None if not best_overall else best_overall.get("name"),
        "best_overall_sharpe": None if not best_overall else best_overall.get("sharpe_ratio"),
        "note": (
            "Primary sort: Sharpe, then max DD (less negative), then total return. "
            "Recommended is best risk-ON config. Risk-only tuning cannot push Sharpe to ~0.6."
        ),
    }
    best_path.write_text(json.dumps(best_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nRe-running winner {rec_name} as search_best for full results...")
    apply_risk_config(profile_body, profile_name="search_best")
    result = run_backtest(frames)
    out_dir = save_full_results("search_best", result, profile_body)
    # Also alias folder by original name
    alias = save_full_results(rec_name, result, profile_body)
    print(f"Results: {out_dir}")
    print(f"Alias:   {alias}")
    print(f"Best config JSON: {best_path}")

    # Top-5 print
    print("\n=== TOP 5 ===")
    cols = [
        "name",
        "sharpe_ratio",
        "annual_return_pct",
        "max_ddpercent",
        "total_return_pct",
        "avg_gross_leverage",
        "days_half",
        "days_flat",
    ]
    print(ok[cols].head(5).to_string(index=False))


if __name__ == "__main__":
    main()
