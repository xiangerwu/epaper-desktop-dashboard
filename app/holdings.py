"""持股設定:存讀 `data/holdings.json`、驗證、盤中判斷、卡片總覽計算。

設定頁 POST 進來的資料在這裡驗證(前端也有同一套規則);報價由
`collectors/stocks.py` 每小時抓進快取,卡片總覽用「目前設定的股數 × 最新快取報價」
即時計算,所以改股數後不必等下次抓價。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from .config import DATA_DIR

HOLDINGS_FILE = DATA_DIR / "holdings.json"
SNAPSHOT_FILE = DATA_DIR / "snapshot.json"
TPE = ZoneInfo("Asia/Taipei")

CODE_RE = re.compile(r"^[0-9]{4,6}[A-Z]?$")
COST_RE = re.compile(r"^[0-9]+(\.[0-9]{1,4})?$")
MAX_SHARES = 10_000_000
MAX_HOLDINGS = 30

DEFAULT_DISPLAY = {"market_hours_only": True, "rotate_seconds": 60, "hide_after_hours": False}
MINUS = "−"  # 全形減號,金額負號用


# ---------- 存讀 ----------

def load() -> dict:
    """讀設定;檔案不存在或損壞時回空設定(卡片不顯示,只剩 Steam)。"""
    try:
        data = json.loads(HOLDINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "version": 1,
        "updated_at": data.get("updated_at"),
        "holdings": data.get("holdings") if isinstance(data.get("holdings"), list) else [],
        "display": {**DEFAULT_DISPLAY, **(data.get("display") or {})},
    }


def write_json_atomic(path, data: Any) -> None:
    """先寫 .tmp 再 rename,斷電不會留下寫一半的檔。"""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save(clean: dict) -> dict:
    data = {
        "version": 1,
        "updated_at": datetime.now(TPE).isoformat(timespec="seconds"),
        **clean,
    }
    write_json_atomic(HOLDINGS_FILE, data)
    return data


# ---------- 驗證 ----------

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate(payload: Any) -> tuple[dict | None, dict[str, str]]:
    """回 (乾淨資料, 錯誤)。錯誤 key 如 `holdings[0].code`、`display.rotate_seconds`。"""
    errors: dict[str, str] = {}
    if not isinstance(payload, dict):
        return None, {"_": "格式錯誤"}

    raw = payload.get("holdings")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_HOLDINGS:
        errors["holdings"] = f"持股需為 1 到 {MAX_HOLDINGS} 筆"
        raw = raw if isinstance(raw, list) else []

    holdings, seen = [], set()
    for i, h in enumerate(raw[:MAX_HOLDINGS]):
        p = f"holdings[{i}]"
        if not isinstance(h, dict):
            errors[p] = "格式錯誤"
            continue
        code = h.get("code")
        if not isinstance(code, str) or not CODE_RE.fullmatch(code):
            errors[f"{p}.code"] = "代號是 4–6 位數字，主動式 ETF 結尾加 A"
        elif code in seen:
            errors[f"{p}.code"] = "這檔已經在列表裡"
        else:
            seen.add(code)

        shares = h.get("shares")
        if not _is_int(shares) or shares <= 0:
            errors[f"{p}.shares"] = "請輸入大於 0 的整數"
        elif shares > MAX_SHARES:
            errors[f"{p}.shares"] = "股數超過上限"

        cost = h.get("avg_cost")
        if cost is not None:
            # 用字串表示檢查小數位數;float 例如 85.2 → "85.2"
            ok = (isinstance(cost, (int, float)) and not isinstance(cost, bool)
                  and cost > 0 and COST_RE.fullmatch(repr(float(cost)).removesuffix(".0")))
            if not ok:
                errors[f"{p}.avg_cost"] = "請輸入大於 0 的數字，最多 4 位小數"

        holdings.append({"code": code, "shares": shares, "avg_cost": cost})

    display = {**DEFAULT_DISPLAY, **(payload.get("display") or {})}
    rs = display.get("rotate_seconds")
    if not _is_int(rs) or not 15 <= rs <= 600:
        errors["display.rotate_seconds"] = "請輸入 15–600 的整數"
    for k in ("market_hours_only", "hide_after_hours"):
        if not isinstance(display.get(k), bool):
            errors[f"display.{k}"] = "需為 true / false"

    if errors:
        return None, errors
    return {"holdings": holdings, "display": {k: display[k] for k in DEFAULT_DISPLAY}}, {}


# ---------- 盤中判斷 ----------

def in_update_window(now: datetime | None = None) -> bool:
    """排程可抓價的時段:週一至週五 09:00–14:00(含 14:00 那次,抓收盤價)。"""
    now = (now or datetime.now(TPE)).astimezone(TPE)
    return now.weekday() < 5 and time(9, 0) <= now.time() <= time(14, 0)


def in_trading_session(now: datetime | None = None) -> bool:
    """實際交易中:週一至週五 09:00–13:30。用於標題「盤中/收盤」與收盤後不輪播。"""
    now = (now or datetime.now(TPE)).astimezone(TPE)
    return now.weekday() < 5 and time(9, 0) <= now.time() < time(13, 30)


# ---------- 卡片總覽 ----------

def _sym(pct: float) -> str:
    return "▲" if pct > 0 else "▼" if pct < 0 else "—"


def _pct(pct: float) -> str:
    return f"{_sym(pct)}{abs(pct):.2f}%"


def _money(n: float) -> str:
    return f"{MINUS if n < 0 else '+'}NT$ {abs(round(n)):,}"


def _signed_pct(pct: float) -> str:
    return f"{MINUS if pct < 0 else '+'}{abs(pct):.2f}%"


def short_name(name: str) -> str:
    return name if len(name) <= 8 else name[:7] + "…"


def summarize(config: dict, snapshot: dict | None, now: datetime | None = None,
              age_seconds: int | None = None) -> dict | None:
    """設定股數 × 快照報價 → 卡片欄位。沒有任何持股設定時回 None(不顯示卡片)。

    報價缺漏的持股不計入任何總計,只在檔數統計後加註「N 檔無報價」。
    """
    holdings = config.get("holdings") or []
    if not holdings:
        return None
    quotes = {q["code"]: q for q in (snapshot or {}).get("items", [])
              if q.get("price") and q.get("prev_close")}

    rows = []
    for h in holdings:
        q = quotes.get(h["code"])
        if not q:
            continue
        sh, p, y = h["shares"], q["price"], q["prev_close"]
        cost = h.get("avg_cost")
        rows.append({
            "name": q.get("name") or h["code"],
            "change_pct": (p - y) / y * 100,
            "value": p * sh, "prev_value": y * sh,
            "cost_value": cost * sh if cost else None,
        })
    missing = len(holdings) - len(rows)

    now = (now or datetime.now(TPE)).astimezone(TPE)
    quote_date = (snapshot or {}).get("quote_date")  # "YYYYMMDD"
    if in_trading_session(now) and quote_date == now.strftime("%Y%m%d"):
        m = (age_seconds or 0) // 60
        status = "盤中・剛更新" if m < 1 else f"盤中・{m} 分前"
    elif quote_date:
        status = f"收盤・{quote_date[4:6]}/{quote_date[6:8]}"
    else:
        status = "無報價"

    card: dict[str, Any] = {"status": status, "count": len(holdings), "missing": missing,
                            "has_quotes": bool(rows)}
    if not rows:
        return card

    V = sum(r["value"] for r in rows)
    PV = sum(r["prev_value"] for r in rows)
    day = V - PV
    day_pct = day / PV * 100 if PV else 0.0
    with_cost = [r for r in rows if r["cost_value"] is not None]
    lo = min(rows, key=lambda r: r["change_pct"])
    hi = max(rows, key=lambda r: r["change_pct"])

    card.update({
        "day_pct": _pct(day_pct),
        "day_pnl": _money(day),
        "down": sum(1 for r in rows if r["change_pct"] < 0),
        "up": sum(1 for r in rows if r["change_pct"] > 0),
        "total_value": f"{round(V):,}",
        "weakest": {"name": short_name(lo["name"]), "pct": _pct(lo["change_pct"])},
        "strongest": {"name": short_name(hi["name"]), "pct": _pct(hi["change_pct"])},
    })
    if with_cost:
        C = sum(r["cost_value"] for r in with_cost)
        U = sum(r["value"] for r in with_cost) - C
        card["unrealized"] = {
            "value": _money(U), "sub": _signed_pct(U / C * 100),
            "note": "部分未填成本" if len(with_cost) < len(rows) else "",
        }
    else:
        card["unrealized"] = {"value": "--", "sub": "未填平均成本", "note": ""}
    return card
