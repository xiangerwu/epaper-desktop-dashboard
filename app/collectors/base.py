"""Collector 介面。"""
from __future__ import annotations

import abc
import logging

from .. import cache

log = logging.getLogger("collector")


class Collector(abc.ABC):
    #: cache key,也是排程 job id
    source: str
    #: 收集節奏(秒)
    interval_seconds: int = 900

    @abc.abstractmethod
    async def fetch(self) -> dict:
        """抓一次資料,回傳可 JSON 序列化的 dict。失敗就 raise。"""

    async def run(self) -> None:
        """排程呼叫這個。抓成功才覆寫 cache;失敗保留舊值。"""
        try:
            payload = await self.fetch()
            cache.put(self.source, payload)
            log.info("collected %s", self.source)
        except Exception:  # noqa: BLE001 - 單源失敗不可拖垮其他源
            log.exception("collect %s failed; keeping stale cache", self.source)
