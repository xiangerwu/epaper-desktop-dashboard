"""農民曆宜忌 collector:爬好日網(goodaytw.com)首頁的「今日宜忌」。

好日網是政府資料開放平臺應用展示的台灣農民曆網站(data.gov.tw/applications/136072);
其宜忌為自家內容,平臺上標示使用的政府資料集只有「政府行政機關辦公日曆表」。

robots.txt(2026-09 實測):`Allow: /`,但 `Disallow: /20*-*-*` —— 日期頁(/2026-09-29)禁止爬取。
所以只抓首頁,首頁本身顯示當天宜忌;一天最多 3 次(00:05、06:05、12:05,後兩次是重試)。

首頁結構(MUI SSR,2026-09):日期標頭 `2026/09/29 (二)`,其後第一組
  <div class="...__yiO ...">宜</div></div><style>…</style><div class="...infoGrid2...">祭祀、冠笄…</div>
  <div class="...__jiO ...">忌</div></div><div class="...infoGrid2...">嫁娶、開市…</div>
頁面後段還有「各時辰宜忌」,結構相似,所以只取日期標頭後的第一組。
頁面日期必須等於今天(台北時間)才採用,否則 raise、保留上次結果;看板只顯示今天的資料。
"""
from __future__ import annotations

import re
from datetime import datetime

from .. import holdings
from ..net import client
from .base import Collector

URL = "https://www.goodaytw.com/"
HEADERS = {"User-Agent": "epaper-dashboard/1.0 (personal)"}
_DATE = re.compile(r"(\d{4})/(\d{2})/(\d{2}) \(")


def parse(page: str) -> dict:
    """首頁 HTML → {"date": "YYYY-MM-DD", "yi": [...], "ji": [...]};結構不符就 raise。"""
    page = re.sub(r"<style[^>]*>.*?</style>", "", page, flags=re.S)
    d = _DATE.search(page)
    if not d:
        raise ValueError("找不到日期標頭")
    rest = page[d.end():]
    out = {"date": f"{d[1]}-{d[2]}-{d[3]}"}
    for key, label in (("yi", "宜"), ("ji", "忌")):
        m = re.search(rf'class="[^"]*__{key}O[^"]*"\s*>\s*{label}\s*</div>\s*</div>\s*'
                      rf'<div[^>]*infoGrid2[^>]*>([^<]+)</div>', rest)
        if not m:
            raise ValueError(f"找不到{label}")
        out[key] = [x.strip() for x in m[1].split("、") if x.strip()]
    return out


class AlmanacCollector(Collector):
    source = "almanac"
    interval_seconds = 6 * 3600  # 供 /health 判 stale
    cron_minute = 5
    cron_hour = "0,6,12"

    async def fetch(self) -> dict:
        async with client() as c:
            r = await c.get(URL, headers=HEADERS, follow_redirects=True)
        r.raise_for_status()
        data = parse(r.text)
        today = datetime.now(holdings.TPE).strftime("%Y-%m-%d")
        if data["date"] != today:
            raise ValueError(f"首頁日期 {data['date']} 不是今天 {today}")
        return {**data, "source": "goodaytw.com"}
