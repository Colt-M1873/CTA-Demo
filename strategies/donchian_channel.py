# -*- coding: utf-8 -*-
"""Donchian Channel (Turtle-style) trend CTA — long/short, fixed 1 lot.

Entry: close breaks above prior entry_window high -> long;
       close breaks below prior entry_window low  -> short.
Exit:  long  exits when close breaks below prior exit_window low;
       short exits when close breaks above prior exit_window high.
Opposite entry breakout also reverses the position.

Channel uses PRIOR bars only (excludes current bar) to avoid look-ahead on daily closes.
"""

from __future__ import annotations

from vnpy_ctastrategy import (
    CtaTemplate,
    StopOrder,
    TickData,
    BarData,
    TradeData,
    OrderData,
    BarGenerator,
    ArrayManager,
)


class DonchianChannelStrategy(CtaTemplate):
    """Classic Donchian / Turtle entry-exit channel, no pyramiding."""

    author = "vnpy-learning"

    entry_window: int = 20
    exit_window: int = 10
    fixed_size: int = 1

    entry_up: float = 0.0
    entry_down: float = 0.0
    exit_up: float = 0.0
    exit_down: float = 0.0

    parameters = ["entry_window", "exit_window", "fixed_size"]
    variables = ["entry_up", "entry_down", "exit_up", "exit_down"]

    def on_init(self) -> None:
        self.write_log("DonchianChannelStrategy init")
        self.bg = BarGenerator(self.on_bar)
        # Need entry_window+2 for prior-bar channel; default 100 is fine for daily.
        self.am = ArrayManager(size=max(100, self.entry_window + 5))
        self.load_bar(self.entry_window + 5)

    def on_start(self) -> None:
        self.write_log("DonchianChannelStrategy start")
        self.put_event()

    def on_stop(self) -> None:
        self.write_log("DonchianChannelStrategy stop")
        self.put_event()

    def on_tick(self, tick: TickData) -> None:
        self.bg.update_tick(tick)

    def on_bar(self, bar: BarData) -> None:
        self.cancel_all()

        am = self.am
        am.update_bar(bar)
        if not am.inited:
            return

        # Prior N-bar channel (exclude current bar) — no look-ahead on same-bar close.
        entry_up_arr, entry_down_arr = am.donchian(self.entry_window, array=True)
        exit_up_arr, exit_down_arr = am.donchian(self.exit_window, array=True)

        self.entry_up = float(entry_up_arr[-2])
        self.entry_down = float(entry_down_arr[-2])
        self.exit_up = float(exit_up_arr[-2])
        self.exit_down = float(exit_down_arr[-2])

        price = bar.close_price
        size = self.fixed_size

        long_entry = price > self.entry_up
        short_entry = price < self.entry_down
        long_exit = price < self.exit_down
        short_exit = price > self.exit_up

        if self.pos == 0:
            if long_entry:
                self.buy(price, size)
            elif short_entry:
                self.short(price, size)
        elif self.pos > 0:
            if short_entry:
                # reverse
                self.sell(price, abs(self.pos))
                self.short(price, size)
            elif long_exit:
                self.sell(price, abs(self.pos))
        elif self.pos < 0:
            if long_entry:
                self.cover(price, abs(self.pos))
                self.buy(price, size)
            elif short_exit:
                self.cover(price, abs(self.pos))

        self.put_event()

    def on_order(self, order: OrderData) -> None:
        pass

    def on_trade(self, trade: TradeData) -> None:
        self.put_event()

    def on_stop_order(self, stop_order: StopOrder) -> None:
        pass
