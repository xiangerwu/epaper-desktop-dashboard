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


def build() -> dict:
    now = datetime.now()

    weather_c = cache.get("weather")
    weather = weather_c["payload"] if weather_c else None
    weather_age = _age_label(weather_c["age_seconds"] if weather_c else None)

    # AI 額度: 兩格,左 Claude 右 Codex。各來源存 {"lines":[{label,pct,detail}...]}
    def _lines(src: str) -> list[dict]:
        c = cache.get(src)
        return c["payload"].get("lines", []) if c else []

    ai_columns = [
        {"name": "Claude", "lines": _lines("anthropic_usage"), "empty": "無資料"},
        {"name": "Codex", "lines": _lines("codex_usage"), "empty": "待憑證"},
    ]

    return {
        "generated_at": now.strftime("%Y/%m/%d  %H:%M"),
        "weekday": "一二三四五六日"[now.weekday()],
        "weather": weather,
        "weather_age": weather_age,
        "ai_columns": ai_columns,
    }
