"""基金設定:存讀 `data/funds.json`、驗證、卡片總覽計算。

與持股模組(`holdings.py`)同一套作法:設定頁 POST 進來先驗證,原子寫檔;
淨值與匯率由 `collectors/funds.py` 每天抓兩次進快取,卡片用「目前設定的單位數/成本 ×
快取最新淨值 × 最新匯率」在渲染時計算。

基金識別:FundClear(基金資訊觀測站)的 API 只認它自己的基金代碼,不接受 ISIN 查詢,
所以每檔同時存 `fundclear_code` + `site`(onshore/offshore)抓淨值,`isin` 供辨識。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .config import DATA_DIR
from .holdings import TPE, _is_int, _money, _pct, write_json_atomic

FUNDS_FILE = DATA_DIR / "funds.json"
SNAPSHOT_FILE = DATA_DIR / "funds_snapshot.json"

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
CODE_RE = re.compile(r"^[A-Za-z0-9]{1,20}$")
UNITS_RE = re.compile(r"^[0-9]+(\.[0-9]{1,4})?$")
CURRENCIES = ("TWD", "USD", "EUR", "JPY", "CNY", "AUD", "ZAR")
SITES = ("onshore", "offshore")
MAX_FUNDS = 20
MAX_NAME = 8

DEFAULT_DISPLAY = {"enabled": True}


# ---------- 存讀 ----------

def load() -> dict:
    """讀設定;檔案不存在或損壞時回空設定(不顯示基金卡片)。"""
    try:
        data = json.loads(FUNDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {
        "version": 1,
        "updated_at": data.get("updated_at"),
        "funds": data.get("funds") if isinstance(data.get("funds"), list) else [],
        "display": {**DEFAULT_DISPLAY, **(data.get("display") or {})},
    }


def save(clean: dict) -> dict:
    data = {"version": 1, "updated_at": datetime.now(TPE).isoformat(timespec="seconds"), **clean}
    write_json_atomic(FUNDS_FILE, data)
    return data


# ---------- 驗證 ----------

def _decimal_ok(v: Any, pattern: re.Pattern) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
            and bool(pattern.fullmatch(repr(float(v)).removesuffix(".0"))))


def validate(payload: Any) -> tuple[dict | None, dict[str, str]]:
    """回 (乾淨資料, 錯誤)。錯誤 key 如 `funds[0].isin`、`display.enabled`。"""
    errors: dict[str, str] = {}
    if not isinstance(payload, dict):
        return None, {"_": "格式錯誤"}

    raw = payload.get("funds")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_FUNDS:
        errors["funds"] = f"基金需為 1 到 {MAX_FUNDS} 筆"
        raw = raw if isinstance(raw, list) else []

    funds, seen = [], set()
    for i, f in enumerate(raw[:MAX_FUNDS]):
        p = f"funds[{i}]"
        if not isinstance(f, dict):
            errors[p] = "格式錯誤"
            continue
        isin = f.get("isin")
        if not isinstance(isin, str) or not ISIN_RE.fullmatch(isin):
            errors[f"{p}.isin"] = "ISIN 是 12 碼，例如 TW000T0101A1"
        elif isin in seen:
            errors[f"{p}.isin"] = "這檔已經在列表裡"
        else:
            seen.add(isin)

        name = f.get("name")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            errors[f"{p}.name"] = "請輸入顯示名稱"
        elif len(name) > MAX_NAME:
            errors[f"{p}.name"] = f"最多 {MAX_NAME} 個字"

        if f.get("currency") not in CURRENCIES:
            errors[f"{p}.currency"] = "不支援的幣別：" + str(f.get("currency"))

        if not _decimal_ok(f.get("units"), UNITS_RE):
            errors[f"{p}.units"] = "大於 0，最多 4 位小數"

        cost = f.get("cost_twd")
        if cost is not None and (not _is_int(cost) or cost <= 0):
            errors[f"{p}.cost_twd"] = "請輸入正整數"

        # FundClear 代碼/站台由設定頁搜尋帶入;沒有也能存,但抓不到淨值(記入 errors)
        code, site = f.get("fundclear_code"), f.get("site")
        if code is not None and (not isinstance(code, str) or not CODE_RE.fullmatch(code)):
            errors[f"{p}.fundclear_code"] = "FundClear 代碼格式錯誤"
        if site is not None and site not in SITES:
            errors[f"{p}.site"] = "site 需為 onshore / offshore"

        funds.append({"isin": isin, "name": name, "currency": f.get("currency"),
                      "units": f.get("units"), "cost_twd": cost,
                      "fundclear_code": code or None, "site": site or None})

    display = {**DEFAULT_DISPLAY, **(payload.get("display") or {})}
    if not isinstance(display.get("enabled"), bool):
        errors["display.enabled"] = "需為 true / false"

    if errors:
        return None, errors
    return {"funds": funds, "display": {"enabled": display["enabled"]}}, {}


# ---------- 卡片總覽 ----------

def _mmdd(iso_date: str) -> str:
    """"2026-09-26" → "09/26"。"""
    return f"{iso_date[5:7]}/{iso_date[8:10]}"


def summarize(config: dict, snapshot: dict | None) -> dict | None:
    """設定單位數/成本 × 快照淨值 × 最新匯率 → 卡片欄位。沒有任何基金時回 None。

    公式見 SPEC-funds-card.md 7.2。漲跌% 用原幣計算(不含匯率變動);
    淨值或匯率缺漏的基金不計入任何總計,只在左欄加註「N 檔無淨值」。
    """
    funds = config.get("funds") or []
    if not funds:
        return None
    snapshot = snapshot or {}
    fx = {**(snapshot.get("fx") or {}), "TWD": 1.0}
    navs = {i["isin"]: i for i in snapshot.get("items", []) if i.get("nav") and i.get("prev_nav")}

    rows = []
    for f in funds:
        q, rate = navs.get(f["isin"]), fx.get(f["currency"])
        if not q or not isinstance(rate, (int, float)):
            continue
        u, nav, prev = f["units"], q["nav"], q["prev_nav"]
        value = nav * u * rate
        cost = f.get("cost_twd")
        rows.append({
            "name": f["name"], "value": value, "prev_value": prev * u * rate,
            "day_pct": (nav - prev) / prev * 100, "cost": cost,
            "ret_pct": (value - cost) / cost * 100 if cost else None,
            "nav_date": q.get("nav_date") or "",
        })

    dates = sorted({r["nav_date"] for r in rows if r["nav_date"]})
    card: dict[str, Any] = {
        "count": len(funds), "missing": len(funds) - len(rows), "has_navs": bool(rows),
        "status": f"淨值日 {_mmdd(dates[-1])}" if dates else "無淨值",
        "earliest": _mmdd(dates[0]) if len(dates) > 1 else "",
    }
    if not rows:
        return card

    V = sum(r["value"] for r in rows)
    PV = sum(r["prev_value"] for r in rows)
    day = V - PV
    with_cost = [r for r in rows if r["cost"]]
    card.update({
        "day_pct": _pct(day / PV * 100 if PV else 0.0),
        "day_pnl": _money(day),
        "total_value": f"{round(V):,}",
        "top": [
            {"name": r["name"], "pct": _pct(r["day_pct"]),
             "ret": "累計 " + (_pct(r["ret_pct"]) if r["ret_pct"] is not None else "--")}
            for r in sorted(rows, key=lambda r: r["value"], reverse=True)[:3]
        ],
    })
    if with_cost:
        C = sum(r["cost"] for r in with_cost)
        U = sum(r["value"] for r in with_cost) - C
        card["profit"] = {"value": _money(U), "sub": _pct(U / C * 100),
                          "note": "部分未填成本" if len(with_cost) < len(rows) else ""}
    else:
        card["profit"] = {"value": "--", "sub": "未填投入成本", "note": ""}
    return card
