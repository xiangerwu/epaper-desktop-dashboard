"""今日電網發電資訊 collector:台電各機組發電量即時資訊(政府開放資料 data.gov.tw/dataset/8931)。

端點(2026-09 實測,政府資料開放授權,不需特殊 header):
  https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json
  {"DateTime": "2026-09-29T15:30:00", "aaData": [{"機組類型","機組名稱","裝置容量(MW)","淨發電量(MW)",...}]}
  每類型有一列 機組名稱 = "小計"(或 "小計(註5)"),數值帶佔比:"15392.0(25.188%)"。
資料集標示每 10 分鐘更新,實測會停住數小時(9/29 15:35 後未更新),所以卡片一併顯示資料時間。
台電官網頁面用的 loadGraph/genary.json 會回機器人驗證頁,不使用。

只存各類型小計;基金卡左欄每次渲染(頁面自動刷新)隨機挑一個類型顯示。
"""
from __future__ import annotations

import re

from ..net import client
from .base import Collector

URL = "https://service.taipower.com.tw/data/opendata/apply/file/d006001/001.json"
HEADERS = {"User-Agent": "epaper-dashboard/1.0 (personal)"}
_NUM_PCT = re.compile(r"^\s*([\d.]+)\s*\(\s*([\d.]+)%\s*\)")
# 類型名稱太長時的顯示名
SHORT = {"民營電廠-燃氣": "民營燃氣", "民營電廠-燃煤": "民營燃煤", "其它再生能源": "其他再生"}


def parse(data: dict) -> dict:
    """台電 JSON → {"time": "HH:MM", "date": "YYYY-MM-DD", "types": [{name, mw, share}]}。

    不算「發電量/裝置容量」:小計列兩者統計範圍不一致(實測燃氣 106%、汽電共生 294%),會誤導。
    """
    types = []
    for row in data.get("aaData") or []:
        if not str(row.get("機組名稱", "")).startswith("小計"):
            continue
        name = re.sub(r"<[^>]+>", "", row.get("機組類型", "")).strip()
        gen = _NUM_PCT.match(row.get("淨發電量(MW)", ""))
        if not name or not gen:
            continue
        types.append({"name": SHORT.get(name, name), "mw": float(gen[1]), "share": float(gen[2])})
    if not types:
        raise ValueError("找不到任何小計列")
    stamp = data.get("DateTime") or ""
    return {"date": stamp[:10], "time": stamp[11:16], "types": types}


class PowerCollector(Collector):
    source = "power"
    interval_seconds = 600

    async def fetch(self) -> dict:
        async with client() as c:
            r = await c.get(URL, headers=HEADERS)
        r.raise_for_status()
        return parse(r.json())
