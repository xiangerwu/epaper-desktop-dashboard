"""天氣 collector: 中央氣象署 CWA 開放資料 F-C0032-001(縣市 36 小時預報)。

取最近一個時段: 天氣現象(Wx)、降雨機率(PoP)、最低/最高溫(MinT/MaxT)、舒適度(CI)。
此資料集無「即時氣溫」,故以高/低溫呈現。
"""
from __future__ import annotations

from ..config import settings
from ..net import client
from .base import Collector

CWA_FORECAST = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"


class WeatherCollector(Collector):
    source = "weather"
    interval_seconds = 600  # 10 分

    async def fetch(self) -> dict:
        if not settings.cwa_api_key:
            raise RuntimeError("CWA_API_KEY 未設定")

        async with client() as c:
            r = await c.get(
                CWA_FORECAST,
                params={
                    "Authorization": settings.cwa_api_key,
                    "locationName": settings.cwa_location,
                },
            )
            r.raise_for_status()
            data = r.json()

        locs = data["records"]["location"]
        rec = next(
            (l for l in locs if l["locationName"] == settings.cwa_location),
            locs[0],
        )
        # {elementName: 最近一個時段的 parameter}
        el = {e["elementName"]: e["time"][0]["parameter"] for e in rec["weatherElement"]}

        return {
            "location": rec["locationName"],
            "desc": el["Wx"]["parameterName"],
            "pop": int(el["PoP"]["parameterName"]),
            "min_t": int(el["MinT"]["parameterName"]),
            "max_t": int(el["MaxT"]["parameterName"]),
            "comfort": el.get("CI", {}).get("parameterName", ""),
        }
