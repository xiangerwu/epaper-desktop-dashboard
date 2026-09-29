"""台股持股報價 collector:TWSE 基本市況報價(MIS),整批一次查。

端點(2026-09 實測):
  https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_0050.tw|otc_0050.tw|...&json=1
  上市/上櫃前綴未知,所以每檔同時帶 tse_ 與 otc_;查不到的那個會回空殼(c 為空字串)。
  欄位:c 代號、n 簡稱、z 最近成交(無成交時為 "-")、pz 上一筆成交、y 昨收、
  b/a 五檔買/賣價(底線分隔)、d 報價日期 YYYYMMDD。收盤後 z 即收盤價。
  盤中集合競價(13:25–13:30)z 會是 "-",依序退回 pz → trade.z → 買賣中價。

TWSE OpenAPI 的 STOCK_DAY_ALL 實測落後數個交易日,不拿來校正收盤;MIS 收盤後即為當日收盤。

排程每小時整點;`display.market_hours_only` 時只在週一至週五 09:00–14:00 抓,
其餘時段保留上次結果(還沒有任何快照時例外,先抓一次讓卡片有資料)。
單檔抓不到就沿用該檔上次報價,並記入 errors。
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from .. import cache, holdings
from ..net import client
from .base import Collector

log = logging.getLogger("collector")


class _HideQuoteUrl(logging.Filter):
    """httpx 的請求日誌會印出完整 ex_ch(= 持有哪幾檔);規格要求日誌不記錄持股內容。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return "getStockInfo" not in record.getMessage()


logging.getLogger("httpx").addFilter(_HideQuoteUrl())

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
MIN_INTERVAL = 5.0  # 兩次請求至少間隔秒數
RETRIES = 2

_lock = asyncio.Lock()
_last_request = 0.0


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _price(m: dict) -> float | None:
    for v in (m.get("z"), m.get("pz"), (m.get("trade") or {}).get("z")):
        if (p := _num(v)) is not None:
            return p
    bid = _num((m.get("b") or "").split("_")[0])
    ask = _num((m.get("a") or "").split("_")[0])
    if bid and ask:
        return round((bid + ask) / 2, 4)
    return bid or ask


def parse(msgs: list[dict]) -> dict[str, dict]:
    """MIS msgArray → {code: {name, price, prev_close, date}};空殼與缺價略過。"""
    out = {}
    for m in msgs:
        code = m.get("c")
        price, prev = _price(m), _num(m.get("y"))
        if not code or price is None or prev is None:
            continue
        out[code] = {"name": m.get("n") or code, "price": price, "prev_close": prev,
                     "date": m.get("d") or ""}
    return out


async def _query(codes: list[str]) -> list[dict]:
    """整批一次查;失敗重試最多 2 次,所有請求間隔至少 5 秒(跨呼叫共用)。"""
    global _last_request
    ex_ch = "|".join(f"{ex}_{c}.tw" for c in codes for ex in ("tse", "otc"))
    async with _lock:
        last_exc: Exception | None = None
        for _ in range(1 + RETRIES):
            wait = _last_request + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            _last_request = time.monotonic()
            try:
                async with client() as c:
                    r = await c.get(MIS_URL, params={"ex_ch": ex_ch, "json": "1", "delay": "0"})
                    r.raise_for_status()
                    data = r.json()
                if data.get("rtcode") != "0000":
                    raise RuntimeError(f"MIS rtcode {data.get('rtcode')}")
                return data.get("msgArray") or []
            except Exception as e:  # noqa: BLE001 - 重試
                last_exc = e
        raise RuntimeError("MIS 報價查詢失敗") from last_exc


class StocksCollector(Collector):
    source = "stocks"
    interval_seconds = 3600  # 供 /health 判 stale
    cron_minute = 0

    async def run(self) -> None:
        config = holdings.load()
        if (config["display"]["market_hours_only"] and not holdings.in_update_window()
                and cache.get(self.source) is not None):
            log.info("skip %s: outside market hours", self.source)
            return
        await super().run()

    async def fetch(self) -> dict:
        config = holdings.load()
        codes = [h["code"] for h in config["holdings"]]
        prev = cache.get(self.source)
        prev_items = {i["code"]: i for i in (prev["payload"].get("items", []) if prev else [])}

        quotes = parse(await _query(codes)) if codes else {}

        items, errors = [], []
        for h in config["holdings"]:
            code = h["code"]
            q = quotes.get(code)
            if q is None:
                old = prev_items.get(code)
                errors.append({"code": code,
                               "reason": "查無報價,沿用上次" if old else "查無報價"})
                if old:
                    items.append({**old, "stale": True})
                continue
            sh, p, y = h["shares"], q["price"], q["prev_close"]
            cost = h.get("avg_cost")
            items.append({
                "code": code, "name": q["name"], "price": p, "prev_close": y,
                "change_pct": round((p - y) / y * 100, 2),
                "value": round(p * sh),
                "day_pnl": round((p - y) * sh),
                "unrealized_pnl": round((p - cost) * sh) if cost else None,
                "date": q["date"],
            })

        dates = [i["date"] for i in items if i.get("date") and not i.get("stale")]
        snapshot = {
            "fetched_at": datetime.now(holdings.TPE).isoformat(timespec="seconds"),
            "quote_date": max(dates) if dates else (prev["payload"].get("quote_date") if prev else None),
            "items": items,
            "errors": errors,
        }
        holdings.write_json_atomic(holdings.SNAPSHOT_FILE, snapshot)
        return snapshot
