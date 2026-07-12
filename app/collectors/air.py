"""空氣品質 collector: 環境部 MOENV 開放資料 AQI(aqx_p_432)。

回傳全台測站陣列;取設定的測站(預設斗六),抓 AQI 與狀態(良好/普通...)。
"""
from __future__ import annotations

from ..config import settings
from ..net import client
from .base import Collector

AQI_URL = "https://data.moenv.gov.tw/api/v2/aqx_p_432"


class AirQualityCollector(Collector):
    source = "air_quality"
    interval_seconds = 3600
    cron_minute = 0

    async def fetch(self) -> dict:
        if not settings.moenv_api_key:
            raise RuntimeError("MOENV_API_KEY 未設定")

        async with client() as c:
            r = await c.get(AQI_URL, params={
                "api_key": settings.moenv_api_key,
                "language": "zh",
                "limit": 1000,
            })
            r.raise_for_status()
            data = r.json()

        recs = data if isinstance(data, list) else data.get("records", [])
        rec = (
            next((x for x in recs if x.get("sitename") == settings.aqi_site), None)
            or next((x for x in recs if x.get("county") == settings.aqi_county), None)
        )
        if not rec:
            raise RuntimeError(f"找不到測站 {settings.aqi_site}/{settings.aqi_county}")

        aqi = (rec.get("aqi") or "").strip()
        return {
            "aqi": int(aqi) if aqi.isdigit() else None,
            "status": rec.get("status", ""),
            "sitename": rec.get("sitename", ""),
            "pm25": (rec.get("pm2.5") or "").strip(),
        }
