"""匯率 collector:臺灣銀行牌告(與基金卡同一份 CSV),給股票/基金卡左欄顯示。

股票卡顯示「1 台幣 = ? 日圓」、基金卡顯示「1 美元 = ? 台幣」。
用即期買入/賣出的中價(CSV index 3 / 13),不是任一邊的牌告價。

每小時第 10 分抓一次(臺銀營業時間內會多次改牌,夜間重抓到同一份也無妨)。
`prev` 保存「前一個牌告日」的最後一筆,卡片用它算較前日漲跌;換日時把上次的值滾進 prev。
"""
from __future__ import annotations

import csv
import io
import re

from .. import cache
from .base import Collector
from .funds import _num, _throttled, fetch_bot_csv

CURRENCIES = ("USD", "JPY")


def parse(text: str, filename: str = "") -> dict:
    """BoT 牌告 CSV → {"date": "YYYY-MM-DD", "time": "HH:MM", "USD": 中價, "JPY": 中價}。"""
    out: dict = {}
    for row in csv.reader(io.StringIO(text.lstrip("﻿"))):
        if len(row) > 13 and row[0].strip() in CURRENCIES and row[1] == "本行買入":
            buy, sell = _num(row[3]), _num(row[13])
            if buy and sell:
                out[row[0].strip()] = round((buy + sell) / 2, 5)
    missing = [c for c in CURRENCIES if c not in out]
    if missing:
        raise RuntimeError(f"匯率 CSV 缺 {', '.join(missing)}")
    m = re.search(r"@(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})", filename)
    if not m:
        raise RuntimeError("找不到牌告時間")
    return {"date": f"{m[1]}-{m[2]}-{m[3]}", "time": f"{m[4]}:{m[5]}", **out}


def roll(new: dict, old: dict | None) -> dict:
    """接上前日值:舊值是更早的牌告日 → 它就是新的 prev;同一天 → 沿用舊的 prev。"""
    old = old or {}
    if old.get("date") and old["date"] < new["date"]:
        prev = {k: old[k] for k in ("date", *CURRENCIES) if k in old}
    else:
        prev = old.get("prev")
    return {**new, "prev": prev}


class FxCollector(Collector):
    source = "fx"
    interval_seconds = 3600
    cron_minute = 10

    async def fetch(self) -> dict:
        data = parse(*await _throttled(fetch_bot_csv))
        old = cache.get(self.source)
        return roll(data, old["payload"] if old else None)
