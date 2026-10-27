# -*- coding: utf-8 -*-
"""Connect SimNow CTP, subscribe one night-session contract, print ticks."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG, EVENT_TICK, EVENT_CONTRACT
from vnpy.trader.object import SubscribeRequest
from vnpy_ctp import CtpGateway

SETTING_PATH = Path(__file__).with_name("simnow_ctp_setting.json")
OUT_PATH = Path(__file__).with_name("last_tick_log.txt")
PREFERRED = ("au", "ag", "rb", "m", "i", "hc", "bu", "ru", "TA", "MA", "SA", "sc", "fu")


def load_setting() -> dict:
    data = json.loads(SETTING_PATH.read_text(encoding="utf-8"))
    if not data.get("用户名") or not data.get("密码"):
        print("missing credentials")
        sys.exit(1)
    return data


def pick_contract(contracts: list):
    ranked = []
    for c in contracts:
        for i, pref in enumerate(PREFERRED):
            if c.symbol.startswith(pref) and any(ch.isdigit() for ch in c.symbol):
                ranked.append((i, len(c.symbol), c))
                break
    if ranked:
        ranked.sort(key=lambda x: (x[0], x[1]))
        return ranked[0][2]
    for c in contracts:
        if any(ch.isdigit() for ch in c.symbol):
            return c
    return None


def main() -> None:
    setting = load_setting()
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtpGateway)

    logs: list[str] = []
    ticks: list[str] = []
    got_contract_query = {"ok": False}

    def on_log(event):
        msg = f"[LOG][{event.data.gateway_name}] {event.data.msg}"
        print(msg, flush=True)
        logs.append(msg)
        if "合约信息查询成功" in event.data.msg:
            got_contract_query["ok"] = True

    def on_tick(event):
        t = event.data
        line = (
            f"[TICK] {t.vt_symbol} last={t.last_price} "
            f"bid={t.bid_price_1} ask={t.ask_price_1} vol={t.volume} time={t.datetime}"
        )
        print(line, flush=True)
        ticks.append(line)

    event_engine.register(EVENT_LOG, on_log)
    event_engine.register(EVENT_TICK, on_tick)

    print("connecting...", flush=True)
    main_engine.connect(setting, "CTP")

    for _ in range(60):
        time.sleep(0.5)
        if got_contract_query["ok"]:
            time.sleep(1)
            break

    contracts = list(main_engine.get_all_contracts())
    print(f"contracts_loaded={len(contracts)}", flush=True)
    c = pick_contract(contracts)
    if c is None:
        print("no suitable contract found", flush=True)
        main_engine.close()
        OUT_PATH.write_text("\n".join(logs), encoding="utf-8")
        sys.exit(2)

    print(f"subscribe {c.symbol} exchange={c.exchange}", flush=True)
    main_engine.subscribe(SubscribeRequest(symbol=c.symbol, exchange=c.exchange), "CTP")

    deadline = time.time() + 25
    while time.time() < deadline and len(ticks) < 5:
        time.sleep(0.5)

    main_engine.close()
    summary = [
        f"contracts={len(contracts)}",
        f"subscribed={c.vt_symbol}",
        f"ticks={len(ticks)}",
        "",
        *ticks[:20],
        "",
        *logs[-40:],
    ]
    OUT_PATH.write_text("\n".join(summary), encoding="utf-8")
    print(f"--- done ticks={len(ticks)} ---", flush=True)
    if not ticks:
        sys.exit(3)


if __name__ == "__main__":
    main()
