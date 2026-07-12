"""FastAPI 服務。裝置瀏覽器直接開 `/` 顯示看板(live HTML,不產圖)。

路由:
  GET /        看板頁面(即時渲染;可選 meta 自動刷新)
  GET /health  健康檢查(含各來源快取新鮮度)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from . import cache, scheduler
from .collectors import COLLECTORS
from .config import settings
from .render import html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    for c in COLLECTORS:  # 啟動先抓一輪,首個請求就有資料
        await c.run()
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="pi-eink-dashboard", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return html.render(auto_refresh_seconds=settings.html_auto_refresh_seconds)


@app.get("/health")
async def health():
    sources = {c.source: cache.get(c.source) is not None for c in COLLECTORS}
    return JSONResponse({"ok": True, "sources": sources})


def _port_free(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((settings.host, port))
            return True
        except OSError:
            return False


def _choose_port() -> int:
    """主埠可用就用主埠;否則依序試備用埠。找不到就回主埠讓它明確報錯。"""
    for p in (settings.port, *settings.fallback_ports):
        if _port_free(p):
            if p != settings.port:
                logging.getLogger("main").warning(
                    "主埠 %d 被占用,改用備用埠 %d — 記得把裝置 Fully 的 Start URL "
                    "與 .env 的 DASHBOARD_URL 埠號一併改成 %d", settings.port, p, p,
                )
            return p
    return settings.port


def main() -> None:
    import uvicorn

    port = _choose_port()
    logging.getLogger("main").info("serving on http://%s:%d/", settings.host, port)
    uvicorn.run(app, host=settings.host, port=port)


if __name__ == "__main__":
    main()
