# -*- coding: utf-8 -*-
"""SimNow CTP connect demo (headless). Edit simnow_ctp_setting.json first."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from vnpy.event import EventEngine
from vnpy.trader.engine import MainEngine
from vnpy.trader.event import EVENT_LOG
from vnpy_ctp import CtpGateway

SETTING_PATH = Path(__file__).with_name("simnow_ctp_setting.json")


def load_setting() -> dict:
    if not SETTING_PATH.exists():
        print("missing", SETTING_PATH)
        sys.exit(1)
    data = json.loads(SETTING_PATH.read_text(encoding="utf-8"))
    user = data.get("用户名", "")
    pwd = data.get("密码", "")
    if not user or str(user).startswith("YOUR_") or not pwd or str(pwd).startswith("YOUR_"):
        print("fill username/password in", SETTING_PATH.name)
        sys.exit(1)
    return data


def main() -> None:
    setting = load_setting()
    event_engine = EventEngine()
    main_engine = MainEngine(event_engine)
    main_engine.add_gateway(CtpGateway)

    logs = []

    def on_log(event):
        log = event.data
        msg = f"[{log.gateway_name}] {log.msg}"
        print(msg, flush=True)
        logs.append(msg)

    event_engine.register(EVENT_LOG, on_log)

    print("connecting SimNow CTP...", flush=True)
    print("  broker:", setting.get("经纪商代码"), flush=True)
    print("  md:", setting.get("行情服务器"), flush=True)
    print("  td:", setting.get("交易服务器"), flush=True)
    main_engine.connect(setting, "CTP")
    time.sleep(20)
    main_engine.close()
    print("--- done ---", flush=True)
    Path(__file__).with_name("last_connect_log.txt").write_text(
        "\n".join(logs), encoding="utf-8"
    )
    print("log_lines", len(logs), flush=True)


if __name__ == "__main__":
    main()
