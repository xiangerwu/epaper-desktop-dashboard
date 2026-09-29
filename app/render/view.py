"""把 cache 裡各來源的資料組成給模板用的 view-model。

有 collector 的(weather)讀 cache;還沒接的(AI 額度/日曆)先塞假資料佔位。
每塊帶 age 字樣,標出資料新鮮度;來源失敗時讀舊快取,畫面不空白。
"""
from __future__ import annotations

import random
from datetime import datetime

from .. import cache, funds as funds_mod, holdings


def _age_label(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "無資料"
    m = age_seconds // 60
    if m < 1:
        return "剛更新"
    if m < 60:
        return f"{m} 分前"
    return f"{m // 60} 小時前"


def _reset_time_label(epoch: float | None) -> str:
    """Unix epoch 秒 → 本地 月/日 時:分;無值回空字串。"""
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(epoch).astimezone().strftime("%m/%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ""


def _weather_icon(desc: str) -> str:
    """依 CWA 天氣現象文字選圖示 kind。"""
    if any(k in desc for k in ("雨", "雷", "陣")):
        return "rain"
    if "晴" in desc and "雲" in desc:
        return "partly"
    if "晴" in desc:
        return "sunny"
    return "cloudy"


def build() -> dict:
    now = datetime.now()

    weather_c = cache.get("weather")
    weather = weather_c["payload"] if weather_c else None
    weather_age = _age_label(weather_c["age_seconds"] if weather_c else None)

    air_c = cache.get("air_quality")
    air = air_c["payload"] if air_c else None

    # AI 額度: 兩格,左 Claude 右 Codex。各來源存 {"lines":[{label,pct,detail}...]}
    def _column(name: str, src: str, empty: str) -> dict:
        c = cache.get(src)
        return {
            "name": name,
            "lines": c["payload"].get("lines", []) if c else [],
            "age": _age_label(c["age_seconds"] if c else None),
            "empty": empty,
        }

    ai_columns = [
        {**_column("Claude", "anthropic_usage", "無資料"), "icon": "claude"},
        {**_column("Codex", "codex_usage", "待憑證"), "icon": "openai"},
    ]

    routine_c = cache.get("routine")
    routine = {
        "emoji": "🌙",
        "message": "等待下一次更新",
        "cycle_step": None,
        "remaining_updates": None,
        **(routine_c["payload"] if routine_c else {}),
    }

    steam_c = cache.get("steam")
    steam_payload = steam_c["payload"] if steam_c else {}
    top = steam_payload.get("top")
    if top and isinstance(top.get("latest"), dict):
        top = {**top, "latest": {
            **top["latest"],
            "unlock_label": _reset_time_label(top["latest"].get("unlock_epoch")),
        }}
    steam = {
        "summary": steam_payload.get("summary"),
        "top": top if isinstance(top, dict) else None,
        "age": _age_label(steam_c["age_seconds"] if steam_c else None),
    }

    # 台股持股:與 Steam 共用右下格位輪播。沒設定持股 → 不顯示;
    # 收盤後且 hide_after_hours → 只顯示 Steam。
    config = holdings.load()
    stocks_c = cache.get("stocks")
    stocks = holdings.summarize(
        config, stocks_c["payload"] if stocks_c else None,
        age_seconds=stocks_c["age_seconds"] if stocks_c else None,
    )
    disp = config["display"]
    if stocks and disp["hide_after_hours"] and not holdings.in_trading_session():
        stocks = None
    if stocks:
        # 農民曆宜忌:只在快取是今天的資料時顯示,不拿昨天的充當今天
        alm_c = cache.get("almanac")
        alm = alm_c["payload"] if alm_c else None
        today = datetime.now(holdings.TPE).strftime("%Y-%m-%d")
        stocks["almanac"] = alm if alm and alm.get("date") == today else None

    # 基金:接在股票後輪播;display.enabled = false 時跳過。
    funds_cfg = funds_mod.load()
    funds_c = cache.get("funds")
    funds = (funds_mod.summarize(funds_cfg, funds_c["payload"] if funds_c else None)
             if funds_cfg["display"]["enabled"] else None)
    if funds:
        # 今日電網:每次渲染(頁面自動刷新)隨機挑一個發電類型
        power_c = cache.get("power")
        p = power_c["payload"] if power_c else None
        if p and p.get("types"):
            t = random.choice(p["types"])
            today = datetime.now(holdings.TPE).strftime("%Y-%m-%d")
            stamp = p["time"] if p["date"] == today else f'{p["date"][5:7]}/{p["date"][8:10]} {p["time"]}'
            funds["power"] = {**t, "stamp": stamp}

    return {
        "generated_at": now.strftime("%Y/%m/%d  %H:%M"),
        "weekday": "一二三四五六日"[now.weekday()],
        "weather": weather,
        "weather_age": weather_age,
        "weather_icon": _weather_icon(weather["desc"]) if weather else "cloudy",
        "air": air,
        "ai_columns": ai_columns,
        "routine": routine,
        "steam": steam,
        "stocks": stocks,
        "funds": funds,
        "rotate_seconds": disp["rotate_seconds"],
    }
