"""OpenRouter 額度: GET https://openrouter.ai/api/v1/credits

參考 openusage(docs/providers/openrouter.md)。使用者自填 API key(Bearer)。
回傳 total_credits / total_usage。只在 OPENROUTER_API_KEY 有設時才註冊。
"""
from __future__ import annotations

from ..config import settings
from ..net import client
from .base import Collector

CREDITS_URL = "https://openrouter.ai/api/v1/credits"


class OpenRouterCollector(Collector):
    source = "openrouter"
    interval_seconds = 3600

    async def fetch(self) -> dict:
        key = settings.openrouter_api_key
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY 未設定")

        async with client() as c:
            r = await c.get(CREDITS_URL, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            d = r.json().get("data", {})

        total = float(d.get("total_credits", 0) or 0)
        used = float(d.get("total_usage", 0) or 0)
        pct = round(used / total * 100) if total else 0
        return {"lines": [{
            "label": "OpenRouter",
            "pct": pct,
            "detail": f"${used:.1f} / ${total:.0f}",
        }]}
