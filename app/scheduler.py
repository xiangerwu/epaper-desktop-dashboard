"""排程: 各 collector 依自己節奏更新快取。

頁面是 live HTML(每次請求即時渲染),不需渲染 job。
若開 REFRESH_VIA_ADB,另跑一個 job 定時叫裝置重載頁面 + 喚醒。
"""
from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .collectors import COLLECTORS
from .config import settings

log = logging.getLogger("scheduler")
_sched = AsyncIOScheduler()


async def _adb_refresh() -> None:
    from .device import adb

    # adb 是阻塞式 subprocess,丟到執行緒避免卡事件迴圈
    await asyncio.to_thread(adb.refresh)


def start() -> None:
    for c in COLLECTORS:
        if c.cron_minute is not None:
            _sched.add_job(c.run, "cron", minute=c.cron_minute, id=c.source)
        else:
            # lifespan 已首抓；interval 預設會從現在起算下一次，不可傳 None（會永久暫停）。
            _sched.add_job(
                c.run, "interval", seconds=c.interval_seconds, id=c.source
            )
    if settings.refresh_via_adb:
        _sched.add_job(
            _adb_refresh, "interval",
            seconds=settings.adb_refresh_seconds, id="adb_refresh",
        )
    _sched.start()
    log.info("scheduler started: %d collectors, adb_refresh=%s",
             len(COLLECTORS), settings.refresh_via_adb)


def shutdown() -> None:
    _sched.shutdown(wait=False)
