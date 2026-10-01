"""基金淨值 + 匯率 collector:FundClear(基金資訊觀測站)+ 臺灣銀行牌告匯率。

淨值(2026-09 實測,集保 fundclear.com.tw 前端用的 JSON API,無公開文件):
  POST /api/{onshore|offshore}/nav-profit/query-five-dates
       {"queryType":"0","searchName":<FundClear 代碼>, ...}
  回最近 5 個淨值日:`dateList` 由舊到新;`oneDate` 是最新(= dateList[-1]),
  `twoDate` 前一筆……。值是字串,可能帶千分位逗號,缺值為 "" 或 "-"。
  API 不接受 ISIN 查詢,所以設定存 FundClear 代碼;ISIN 由 query-details 取得。
  舊的「境外基金資訊觀測站」與境內公告平台已於 2025-04-21 併入此站。

匯率:https://rate.bot.com.tw/xrt/flcsv/0/day,欄位 [幣別, 本行買入, 現金, 即期, ...],
  取「即期買入」(index 3,0 表示無)。預設 User-Agent 會被機器人驗證頁擋下,
  需帶瀏覽器 UA + Accept-Language 才拿到 CSV(使用者已同意)。檔名帶牌告時間。

排程每天 08:30、21:00。境外淨值晚 1–2 個營業日屬正常。
單檔失敗沿用上次淨值並記入 errors;匯率失敗沿用上次匯率。
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import time
from datetime import datetime

from .. import cache, funds
from ..net import client
from .base import Collector

log = logging.getLogger("collector")

FC = "https://www.fundclear.com.tw"
FC_HEADERS = {"Content-Type": "application/json", "Accept": "application/json", "Referer": FC + "/"}
BOT_CSV = "https://rate.bot.com.tw/xrt/flcsv/0/day"
BROWSER = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/140.0 Safari/537.36",
    "Accept-Language": "zh-TW",
}
MIN_INTERVAL = 5.0  # 排程抓取時,對同一站台的請求至少間隔秒數
RETRIES = 2
DATE_KEYS = ("oneDate", "twoDate", "threeDate", "fourDate", "fiveDate")

# FundClear 回的中文幣別 → 代碼(取自其 /api/search/fund/init-selection 的 currencyOptions)
CURRENCY_NAMES = {
    "新台幣": "TWD", "台幣": "TWD", "美元": "USD", "歐元": "EUR", "日幣": "JPY", "日圓": "JPY",
    "人民幣": "CNY", "澳幣": "AUD", "南非幣": "ZAR", "英鎊": "GBP", "港幣": "HKD",
    "加幣": "CAD", "瑞士法郎": "CHF", "新加坡幣": "SGD", "紐西蘭幣": "NZD",
    "瑞典幣": "SEK", "泰幣": "THB", "馬來幣": "MYR",
}

_lock = asyncio.Lock()
_last_request = 0.0


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


async def _throttled(fn):
    """排程抓取共用:請求間隔至少 5 秒,失敗重試最多 2 次。"""
    global _last_request
    async with _lock:
        last_exc: Exception | None = None
        for _ in range(1 + RETRIES):
            wait = _last_request + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request = time.monotonic()
            try:
                return await fn()
            except Exception as e:  # noqa: BLE001 - 重試
                last_exc = e
        raise last_exc  # type: ignore[misc]


# ---------- FundClear ----------

async def _fc_post(path: str, body: dict) -> dict | None:
    """回 JSON;查無資料(404)回 None。"""
    async with client() as c:
        r = await c.post(FC + path, json=body, headers={**BROWSER, **FC_HEADERS})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def parse_five_dates(data: dict | None, code: str) -> dict | None:
    """五日淨值回應 → {nav, prev_nav, nav_date, prev_nav_date};找不到該代碼或不足兩筆回 None。"""
    d = (data or {}).get("data") or {}
    dates = d.get("dateList") or []
    row = next((x for x in d.get("offshoreQueryResultVO") or []
                if code in (x.get("fundCode"), x.get("fnFundNo"))), None)
    if not row:
        return None
    points = []  # 新 → 舊
    for i, key in enumerate(DATE_KEYS):
        if i >= len(dates):
            break
        nav = _num(row.get(key))
        if nav is not None:
            points.append((dates[len(dates) - 1 - i].replace("/", "-"), nav))
    if len(points) < 2:
        return None
    (d0, n0), (d1, n1) = points[0], points[1]
    return {"nav": n0, "prev_nav": n1, "nav_date": d0, "prev_nav_date": d1}


async def five_dates(site: str, code: str) -> dict | None:
    body = {"queryType": "0", "searchName": code, "fundClassCode": "", "_pageNum": 1, "_pageSize": 10}
    body.update({"orgId": "", "fundNo": ""} if site == "onshore" else {"organizeCode": "", "fundCode": ""})
    return parse_five_dates(await _fc_post(f"/api/{site}/nav-profit/query-five-dates", body), code)


async def search(q: str) -> list[dict]:
    """設定頁用:以名稱或 FundClear 代碼搜尋(API 不支援 ISIN)。"""
    data = await _fc_post("/api/search/fund/query-fund", {
        "_pageNum": 1, "_pageSize": 20, "column": "", "asc": False, "fundSite": "all",
        "searchKey": q, "fundTypeList": ["all"], "currencyList": ["all"],
        "asiFreqList": ["all"], "fundRiskLevelList": ["all"],
    })
    out = []
    for x in (data or {}).get("data") or []:
        if x.get("fundSite") not in funds.SITES or not x.get("fundCode"):
            continue
        out.append({
            "site": x["fundSite"], "code": x["fundCode"], "name": x.get("fundName") or "",
            "currency": CURRENCY_NAMES.get(x.get("currencyName") or "", x.get("currencyName") or ""),
            "dividend": x.get("asiFreq") or "",
            "nav": _num(x.get("navValue")), "nav_date": (x.get("navTxnDate") or "").replace("/", "-"),
        })
    return out


async def lookup(site: str, code: str) -> dict | None:
    """設定頁用:FundClear 代碼 → ISIN、幣別、全名。"""
    data = await _fc_post(f"/api/{site}/fund-basic/query-details", {"fundCode": code})
    bp = (data or {}).get("basicProfile") or {}
    if site == "onshore":
        isin, ccy, name = bp.get("fnIsinCode"), bp.get("fnMoney"), bp.get("fnChName")
    else:
        isin, name = bp.get("isinCode"), bp.get("fundName")
        ccy = CURRENCY_NAMES.get(bp.get("currencyName") or "", bp.get("currencyName"))
    if not isin:
        return None
    return {"site": site, "code": code, "isin": isin, "currency": ccy, "name": name or ""}


# ---------- 臺灣銀行匯率 ----------

def parse_bot_csv(text: str, filename: str = "") -> dict:
    """BoT 牌告 CSV → {"USD": 31.805, ..., "date": "2026-09-29 19:02"};只收即期買入 > 0。"""
    fx: dict = {}
    for row in csv.reader(io.StringIO(text.lstrip("﻿"))):
        if len(row) > 3 and row[1] == "本行買入" and (rate := _num(row[3])) is not None:
            fx[row[0].strip()] = rate
    if not fx:
        raise RuntimeError("匯率 CSV 無資料")
    if m := re.search(r"@(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})", filename):
        fx["date"] = f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}"
    return fx


async def fetch_bot_csv() -> tuple[str, str]:
    """臺銀牌告 CSV → (內容, content-disposition);匯率卡片的 collectors/fx.py 也用這個。"""
    async with client() as c:
        r = await c.get(BOT_CSV, headers=BROWSER, follow_redirects=True)
    r.raise_for_status()
    if "csv" not in (r.headers.get("content-type") or ""):
        raise RuntimeError("臺銀回傳非 CSV(可能是機器人驗證頁)")
    return r.text, r.headers.get("content-disposition") or ""


async def fetch_fx() -> dict:
    return parse_bot_csv(*await fetch_bot_csv())


# ---------- collector ----------

class FundsCollector(Collector):
    source = "funds"
    interval_seconds = 12 * 3600  # 供 /health 判 stale(2× = 一天)
    cron_minute = 30
    cron_hour = "8,21"

    async def fetch(self) -> dict:
        config = funds.load()
        prev = cache.get(self.source)
        prev_payload = prev["payload"] if prev else {}
        prev_items = {i["isin"]: i for i in prev_payload.get("items", [])}
        errors: list[dict] = []

        fx = prev_payload.get("fx") or {}
        if any(f["currency"] != "TWD" for f in config["funds"]):
            try:
                fx = await _throttled(fetch_fx)
            except Exception:  # noqa: BLE001 - 匯率失敗沿用上次
                log.warning("funds: 匯率抓取失敗,沿用上次")
                errors.append({"isin": "", "reason": "匯率抓取失敗,沿用上次"})

        items = []
        for f in config["funds"]:
            isin, code, site = f["isin"], f.get("fundclear_code"), f.get("site")
            q = None
            if code and site:
                try:
                    q = await _throttled(lambda: five_dates(site, code))
                except Exception:  # noqa: BLE001 - 單檔失敗不拖垮整批
                    q = None
            if q is None:
                old = prev_items.get(isin)
                reason = "未設定 FundClear 代碼" if not (code and site) else "查無淨值"
                errors.append({"isin": isin, "reason": reason + (",沿用上次" if old else "")})
                if old:
                    items.append({**old, "stale": True})
                continue
            rate = 1.0 if f["currency"] == "TWD" else fx.get(f["currency"])
            item = {"isin": isin, "currency": f["currency"], **q}
            if isinstance(rate, (int, float)):
                u, cost = f["units"], f.get("cost_twd")
                value = q["nav"] * u * rate
                item.update({
                    "value_twd": round(value),
                    "day_pnl_twd": round((q["nav"] - q["prev_nav"]) * u * rate),
                    "day_pct": round((q["nav"] - q["prev_nav"]) / q["prev_nav"] * 100, 2),
                    "return_pct": round((value - cost) / cost * 100, 2) if cost else None,
                })
            else:
                errors.append({"isin": isin, "reason": f"缺 {f['currency']} 匯率"})
            items.append(item)

        snapshot = {
            "fetched_at": datetime.now(funds.TPE).isoformat(timespec="seconds"),
            "fx": fx, "items": items, "errors": errors,
        }
        funds.write_json_atomic(funds.SNAPSHOT_FILE, snapshot)
        return snapshot
