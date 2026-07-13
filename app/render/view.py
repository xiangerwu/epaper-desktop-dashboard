"""把 cache 裡各來源的資料組成給模板用的 view-model。

有 collector 的(weather)讀 cache;還沒接的(AI 額度/日曆)先塞假資料佔位。
每塊帶 age 字樣,標出資料新鮮度;來源失敗時讀舊快取,畫面不空白。
"""
from __future__ import annotations

from datetime import datetime

from .. import cache


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
    }
