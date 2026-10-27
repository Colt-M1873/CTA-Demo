# -*- coding: utf-8 -*-
"""Multi-symbol Donchian Channel CTA backtest on AKShare continuous daily bars.

Reproducible runner. Uses local strategies/donchian_channel.py and vnpy_ctastrategy
BacktestingEngine with CSV bars injected (no DB).

Defaults (documented):
  entry_window=20, exit_window=10, fixed_size=1 lot
  capital=1_000_000 per symbol backtest
  commission rate=0.0001 of turnover, slippage=1 tick
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from vnpy.trader.constant import Exchange, Interval
from vnpy.trader.object import BarData
from vnpy_ctastrategy.backtesting import BacktestingEngine

BASE = Path(r"C:\Users\Administrator\Desktop\vnpy")
sys.path.insert(0, str(BASE))

from strategies.donchian_channel import DonchianChannelStrategy  # noqa: E402

DATA_DIR = BASE / "data"
OUT_DIR = DATA_DIR / "donchian_results"

ENTRY_WINDOW = 20
EXIT_WINDOW = 10
FIXED_SIZE = 1
CAPITAL = 1_000_000
RATE = 0.0001  # commission as fraction of turnover
GATEWAY = "DB"

# Symbol specs: csv stem, vt symbol pieces, exchange, contract size, pricetick, slippage(ticks*pricetick)
SYMBOLS = [
    {
        "name": "RB",
        "csv": "RB_daily_main_sina.csv",
        "symbol": "RB99",
        "vt_symbol": "RB99.SHFE",
        "exchange": Exchange.SHFE,
        "size": 10,
        "pricetick": 1.0,
        "slippage": 1.0,
    },
    {
        "name": "AU",
        "csv": "AU_daily_main_sina.csv",
        "symbol": "AU99",
        "vt_symbol": "AU99.SHFE",
        "exchange": Exchange.SHFE,
        "size": 1000,
        "pricetick": 0.02,
        "slippage": 0.02,
    },
    {
        "name": "CU",
        "csv": "CU_daily_main_sina.csv",
        "symbol": "CU99",
        "vt_symbol": "CU99.SHFE",
        "exchange": Exchange.SHFE,
        "size": 5,
        "pricetick": 10.0,
        "slippage": 10.0,
    },
    {
        "name": "IF",
        "csv": "IF_daily_main_sina.csv",
        "symbol": "IF99",
        "vt_symbol": "IF99.CFFEX",
        "exchange": Exchange.CFFEX,
        "size": 300,
        "pricetick": 0.2,
        "slippage": 0.2,
    },
]


def load_bars_from_csv(path: Path, symbol: str, exchange: Exchange) -> list[BarData]:
    bars: list[BarData] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row["datetime"][:10], "%Y-%m-%d")
            bars.append(
                BarData(
                    gateway_name=GATEWAY,
                    symbol=symbol,
                    exchange=exchange,
                    datetime=dt,
                    interval=Interval.DAILY,
                    volume=float(row.get("volume") or 0),
                    open_interest=float(row.get("open_interest") or 0),
                    open_price=float(row["open"]),
                    high_price=float(row["high"]),
                    low_price=float(row["low"]),
                    close_price=float(row["close"]),
                )
            )
    bars.sort(key=lambda b: b.datetime)
    return bars


def run_one(spec: dict) -> dict:
    csv_path = DATA_DIR / spec["csv"]
    if not csv_path.exists():
        return {"name": spec["name"], "error": f"missing {csv_path}"}

    bars = load_bars_from_csv(csv_path, spec["symbol"], spec["exchange"])
    if len(bars) < ENTRY_WINDOW + 10:
        return {"name": spec["name"], "error": f"too few bars: {len(bars)}"}

    start, end = bars[0].datetime, bars[-1].datetime

    engine = BacktestingEngine()
    engine.set_parameters(
        vt_symbol=spec["vt_symbol"],
        interval=Interval.DAILY,
        start=start,
        end=end,
        rate=RATE,
        slippage=spec["slippage"],
        size=spec["size"],
        pricetick=spec["pricetick"],
        capital=CAPITAL,
    )
    engine.add_strategy(
        DonchianChannelStrategy,
        {
            "entry_window": ENTRY_WINDOW,
            "exit_window": EXIT_WINDOW,
            "fixed_size": FIXED_SIZE,
        },
    )
    engine.history_data = bars
    engine.output(
        f"[{spec['name']}] Loaded {len(bars)} bars {start.date()} -> {end.date()}"
    )

    engine.run_backtesting()
    df = engine.calculate_result()
    stats = engine.calculate_statistics()

    # Trade-level win rate
    trades = list(engine.trades.values()) if hasattr(engine, "trades") else []
    # Pair round-trips roughly via closed PnL days is already in stats;
    # also count engine trades and win rate from trade list if available.
    trade_count = int(stats.get("total_trade_count") or 0)

    # Win rate from daily net_pnl or from trades: use closed trade pairs if possible
    win_rate = None
    if trades:
        # vnpy TradeData are fills; approximate round-trip PnL from strategy trades is hard.
        # Prefer daily: fraction of profit days among days with nonzero pnl as rough proxy — skip.
        pass

    # Better win rate: from engine's daily results where trading happened — use trade objects
    # Round-trip: consecutive opposing fills. Simple: count profitable closed trades via df.
    closed_wins = closed_losses = 0
    if df is not None and not df.empty and "net_pnl" in df.columns:
        nonzero = df[df["net_pnl"] != 0]["net_pnl"]
        closed_wins = int((nonzero > 0).sum())
        closed_losses = int((nonzero < 0).sum())
        total_nz = closed_wins + closed_losses
        day_win_rate = (closed_wins / total_nz * 100.0) if total_nz else None
    else:
        day_win_rate = None

    # Round-trip win rate from trade list (entry+exit pairs)
    rt_wins = rt_losses = 0
    if trades:
        # Sort by datetime; accumulate position PnL naively not available on TradeData.
        # Use engine.get_all_trades if present
        pass
    try:
        all_trades = engine.get_all_trades()
    except Exception:
        all_trades = trades

    # Compute round-trip win rate from sequential fills with direction flip
    # Each TradeData has direction, price, volume. Track average entry.
    from vnpy.trader.constant import Direction

    pos = 0
    entry_price = 0.0
    entry_vol = 0
    rt_pnls: list[float] = []
    for t in all_trades:
        sign = 1 if t.direction == Direction.LONG else -1
        # Opening increases |pos| in trade direction relative to prior...
        # Simpler inventory accounting:
        qty = t.volume
        if t.direction == Direction.LONG:
            # buy or cover
            if pos < 0:
                # covering short
                close_vol = min(qty, abs(pos))
                pnl = (entry_price - t.price) * close_vol * spec["size"]
                rt_pnls.append(pnl)
                pos += close_vol
                qty -= close_vol
                if pos == 0:
                    entry_price = 0.0
                if qty > 0:
                    entry_price = t.price
                    pos += qty
            else:
                # adding long
                new_pos = pos + qty
                entry_price = (
                    (entry_price * pos + t.price * qty) / new_pos if new_pos else t.price
                )
                pos = new_pos
        else:
            # SELL / SHORT
            if pos > 0:
                close_vol = min(qty, pos)
                pnl = (t.price - entry_price) * close_vol * spec["size"]
                rt_pnls.append(pnl)
                pos -= close_vol
                qty -= close_vol
                if pos == 0:
                    entry_price = 0.0
                if qty > 0:
                    entry_price = t.price
                    pos -= qty
            else:
                new_pos = pos - qty  # more short
                old = abs(pos)
                entry_price = (
                    (entry_price * old + t.price * qty) / (old + qty)
                    if (old + qty)
                    else t.price
                )
                pos = new_pos

    if rt_pnls:
        rt_wins = sum(1 for p in rt_pnls if p > 0)
        rt_losses = sum(1 for p in rt_pnls if p <= 0)
        win_rate = rt_wins / len(rt_pnls) * 100.0
    else:
        win_rate = None

    equity_path = OUT_DIR / f"equity_{spec['name']}.csv"
    if df is not None and not df.empty:
        cols = [c for c in ["net_pnl", "balance", "drawdown"] if c in df.columns]
        df[cols].to_csv(equity_path, encoding="utf-8-sig")

    result = {
        "name": spec["name"],
        "vt_symbol": spec["vt_symbol"],
        "csv": str(csv_path),
        "start": str(start.date()),
        "end": str(end.date()),
        "bars": len(bars),
        "size": spec["size"],
        "pricetick": spec["pricetick"],
        "slippage": spec["slippage"],
        "capital": CAPITAL,
        "rate": RATE,
        "entry_window": ENTRY_WINDOW,
        "exit_window": EXIT_WINDOW,
        "fixed_size": FIXED_SIZE,
        "total_return_pct": float(stats.get("total_return") or 0),
        "annual_return_pct": float(stats.get("annual_return") or 0),
        "max_ddpercent": float(stats.get("max_ddpercent") or 0),
        "max_drawdown": float(stats.get("max_drawdown") or 0),
        "sharpe_ratio": float(stats.get("sharpe_ratio") or 0),
        "total_net_pnl": float(stats.get("total_net_pnl") or 0),
        "end_balance": float(stats.get("end_balance") or 0),
        "total_trade_count": trade_count,
        "round_trips": len(rt_pnls),
        "win_rate_pct": None if win_rate is None else round(win_rate, 2),
        "profit_days": int(stats.get("profit_days") or 0),
        "loss_days": int(stats.get("loss_days") or 0),
        "day_win_rate_pct": None if day_win_rate is None else round(day_win_rate, 2),
        "total_commission": float(stats.get("total_commission") or 0),
        "total_slippage": float(stats.get("total_slippage") or 0),
        "equity_csv": str(equity_path),
        "raw_stats": {k: (float(v) if isinstance(v, (int, float)) else str(v)) for k, v in stats.items()},
    }
    return result


def portfolio_equal_weight(results: list[dict]) -> dict | None:
    """Equal-weight daily return portfolio from per-symbol equity CSVs."""
    import pandas as pd

    frames = []
    for r in results:
        if r.get("error"):
            continue
        path = Path(r["equity_csv"])
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        if "balance" not in df.columns:
            continue
        s = df["balance"].pct_change().rename(r["name"])
        frames.append(s)
    if len(frames) < 2:
        return None
    aligned = pd.concat(frames, axis=1).dropna(how="all")
    # equal weight among available symbols that day
    port = aligned.mean(axis=1, skipna=True).dropna()
    if port.empty:
        return None
    equity = (1 + port).cumprod() * CAPITAL
    total_return = (equity.iloc[-1] / CAPITAL - 1) * 100
    # annualize: assume ~252 trading days
    n = len(port)
    years = n / 252.0
    ann = ((equity.iloc[-1] / CAPITAL) ** (1 / years) - 1) * 100 if years > 0 else 0
    # max drawdown
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min() * 100)
    # sharpe (daily, *sqrt(252))
    vol = float(port.std())
    sharpe = float(port.mean() / vol * (252 ** 0.5)) if vol > 1e-12 else 0.0
    out = OUT_DIR / "equity_portfolio_equal_weight.csv"
    pd.DataFrame({"port_ret": port, "balance": equity}).to_csv(out, encoding="utf-8-sig")
    return {
        "symbols": [r["name"] for r in results if not r.get("error")],
        "days": n,
        "total_return_pct": round(total_return, 4),
        "annual_return_pct": round(ann, 4),
        "max_ddpercent": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 4),
        "equity_csv": str(out),
        "note": "Equal-weight daily % returns of independent 1-lot backtests; not a real multi-leg book.",
    }


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in SYMBOLS:
        print("=" * 60)
        r = run_one(spec)
        results.append(r)
        if r.get("error"):
            print(f"ERROR {r['name']}: {r['error']}")
        else:
            print(
                f"{r['name']}: total={r['total_return_pct']:.4f}% "
                f"ann={r['annual_return_pct']:.4f}% "
                f"maxDD={r['max_ddpercent']:.4f}% "
                f"Sharpe={r['sharpe_ratio']:.4f} "
                f"trades={r['total_trade_count']} "
                f"win%={r['win_rate_pct']} "
                f"pnl={r['total_net_pnl']:.2f}"
            )

    port = portfolio_equal_weight(results)

    summary = {
        "strategy": "DonchianChannelStrategy",
        "params": {
            "entry_window": ENTRY_WINDOW,
            "exit_window": EXIT_WINDOW,
            "fixed_size": FIXED_SIZE,
            "capital_per_symbol": CAPITAL,
            "commission_rate": RATE,
            "slippage": "1 tick per symbol",
        },
        "symbols": results,
        "portfolio_equal_weight": port,
    }

    summary_path = OUT_DIR / "summary.json"
    # strip raw_stats from JSON for readability but keep in per-symbol files
    slim = {
        "strategy": summary["strategy"],
        "params": summary["params"],
        "symbols": [
            {k: v for k, v in r.items() if k != "raw_stats"} for r in results
        ],
        "portfolio_equal_weight": port,
    }
    summary_path.write_text(
        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Human-readable report
    lines = [
        "Donchian Channel (Turtle-style) CTA backtest",
        f"entry={ENTRY_WINDOW} exit={EXIT_WINDOW} size={FIXED_SIZE} lot | capital={CAPITAL} | rate={RATE} | slippage=1 tick",
        "Channel uses PRIOR bars only (no same-bar look-ahead).",
        "",
    ]
    for r in results:
        if r.get("error"):
            lines.append(f"## {r['name']}: ERROR {r['error']}")
            continue
        lines += [
            f"## {r['name']} ({r['vt_symbol']})",
            f"  range: {r['start']} -> {r['end']}  bars={r['bars']}",
            f"  contract size={r['size']}  pricetick={r['pricetick']}  slippage={r['slippage']}",
            f"  total_return: {r['total_return_pct']:.4f}%",
            f"  annual_return: {r['annual_return_pct']:.4f}%",
            f"  max_drawdown: {r['max_ddpercent']:.4f}%  (abs {r['max_drawdown']:.2f})",
            f"  Sharpe: {r['sharpe_ratio']:.4f}",
            f"  end_balance: {r['end_balance']:.2f}  net_pnl: {r['total_net_pnl']:.2f}",
            f"  trades: {r['total_trade_count']}  round_trips: {r['round_trips']}  win_rate: {r['win_rate_pct']}%",
            f"  commission: {r['total_commission']:.2f}  slippage_cost: {r['total_slippage']:.2f}",
            "",
        ]
    if port:
        lines += [
            "## Equal-weight portfolio (daily avg of symbol % returns)",
            f"  symbols: {', '.join(port['symbols'])}",
            f"  total_return: {port['total_return_pct']:.4f}%",
            f"  annual_return: {port['annual_return_pct']:.4f}%",
            f"  max_drawdown: {port['max_ddpercent']:.4f}%",
            f"  Sharpe: {port['sharpe_ratio']:.4f}",
            f"  note: {port['note']}",
            "",
        ]
    lines += [
        "Caveats:",
        "- Continuous main-force series (AKShare sina), not true month contracts; rolls/gaps not modeled.",
        "- Costs are simplified (rate + 1 tick); real exchange/broker fees differ by product.",
        "- Fixed 1 lot ignores margin/risk sizing; IF/AU notionals differ a lot vs RB.",
        "- Past backtest ≠ future expectation; trend systems lose in choppy markets.",
    ]
    report_path = OUT_DIR / "report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nSummary JSON: {summary_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
