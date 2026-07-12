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
        "mode": "waiting",
        "title": "作息提醒準備中",
        "message": "等待下一次更新",
        "icon": "focus",
        "cycle_step": None,
        "remaining_updates": None,
        **(routine_c["payload"] if routine_c else {}),
    }

    # 今日行程: 尚未接 Google Calendar,先放佔位資料(見 TODO)
    # TODO: 換成 calendar collector 的 cache.get("calendar")
    calendar = [
        {"time": "14:00", "title": "專案檢查"},
        {"time": "19:30", "title": "閱讀"},
    ]

    return {
        "generated_at": now.strftime("%Y/%m/%d  %H:%M"),
        "weekday": "一二三四五六日"[now.weekday()],
        "weather": weather,
        "weather_age": weather_age,
        "weather_icon": _weather_icon(weather["desc"]) if weather else "cloudy",
        "air": air,
        "ai_columns": ai_columns,
        "routine": routine,
        "calendar": calendar,
    }
