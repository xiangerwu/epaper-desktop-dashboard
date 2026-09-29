"""FastAPI 服務。裝置瀏覽器直接開 `/` 顯示看板(live HTML,不產圖)。

路由:
  GET /        看板頁面(即時渲染;可選 meta 自動刷新)
  GET /health  健康檢查(含各來源快取新鮮度)
  GET /settings、GET|POST /api/holdings、GET /api/snapshot  持股設定(僅內網/Tailscale)
  GET /settings/funds、GET|POST /api/funds、GET /api/funds/snapshot|search|lookup  基金設定(同上)
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import cache, funds, holdings, netinfo, scheduler
from .collectors import COLLECTORS
from .collectors import funds as funds_source
from .collectors.base import Collector
from .collectors.funds import FundsCollector
from .collectors.stocks import StocksCollector
from .config import ROOT, settings
from .render import html

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")


class _HideFundQuery(logging.Filter):
    """存取日誌別留下基金搜尋關鍵字/代碼(規格:日誌不記錄持有內容)。"""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) \
                and args[2].startswith(("/api/funds/search?", "/api/funds/lookup?")):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_HideFundQuery())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 啟動先並行抓一輪,全部完成後才接受首個請求
    await asyncio.gather(*(c.run() for c in COLLECTORS))
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="pi-eink-dashboard", lifespan=lifespan)

# 持股設定頁與 API 只給本機 / 內網 / Tailscale(100.64.0.0/10、fd7a:115c:a1e0::/48)。
_PRIVATE_ONLY = ("/settings", "/api/")
_TAILSCALE = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


def _is_internal(host: str | None) -> bool:
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or any(ip in n for n in _TAILSCALE if ip.version == n.version)


@app.middleware("http")
async def internal_only(request: Request, call_next):
    if request.url.path.startswith(_PRIVATE_ONLY) and not _is_internal(
        request.client.host if request.client else None
    ):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return html.render(auto_refresh_seconds=settings.html_auto_refresh_seconds)


@app.get("/pet/spritesheet.webp", include_in_schema=False)
async def pet_spritesheet():
    return FileResponse(ROOT / "pet" / "spritesheet.webp", media_type="image/webp")


_AUDIO_EXTS = {".wav", ".mp3", ".ogg"}
_SOUND_KINDS = {"start", "end"}


# 須在 StaticFiles mount 之前宣告,否則 /pet/sound/* 會被 mount 攔走。
@app.get("/pet/sound/{kind}/list", include_in_schema=False)
async def pet_sound_list(kind: str):
    """列出 pet/sound/{kind} 底下的音檔 URL(番茄鐘隨機音效用);使用者自備檔案。"""
    if kind not in _SOUND_KINDS:
        return JSONResponse({"error": "unknown kind"}, status_code=404)
    d = ROOT / "pet" / "sound" / kind
    if not d.is_dir():
        return JSONResponse([])
    names = sorted(
        p.name for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTS
    )
    return JSONResponse([f"/pet/sound/{kind}/{name}" for name in names])


# 直接送靜態音檔(list 路由已在上方,先比對故不會被攔)。
app.mount("/pet/sound", StaticFiles(directory=ROOT / "pet" / "sound"), name="pet-sound")


@app.get("/app", response_class=HTMLResponse)
async def app_preview(request: Request):
    """桌面 App 的預覽頁:顯示 LAN IP 與可分享看板網址,內嵌 `/` 即時看板。"""
    ip = netinfo.lan_ip()
    port = request.url.port or settings.port
    share_url = f"http://{ip}:{port}/"
    return html.render_app_preview(share_url=share_url, ip=ip, port=port)


@app.get("/refresh")
async def refresh_now():
    """立即刷新按鈕:當場並行抓一輪各來源,再導回看板顯示最新值。"""
    await asyncio.gather(*(c.run() for c in COLLECTORS))
    return RedirectResponse(url="/", status_code=303)


_stocks = next(c for c in COLLECTORS if isinstance(c, StocksCollector))
_funds = next(c for c in COLLECTORS if isinstance(c, FundsCollector))
_bg: set[asyncio.Task] = set()


def _token_error(request: Request) -> JSONResponse | None:
    """持股/基金設定寫入共用 HOLDINGS_TOKEN。"""
    if not settings.holdings_token:
        return JSONResponse({"error": "伺服器未設定 HOLDINGS_TOKEN,無法儲存"}, status_code=403)
    token = request.headers.get("x-holdings-token", "")
    if not secrets.compare_digest(token.encode(), settings.holdings_token.encode()):
        return JSONResponse({"error": "token 錯誤"}, status_code=401)
    return None


def _run_in_background(collector: Collector) -> None:
    # 走 base.run 略過各 collector 自訂的時段限制;背景跑,不讓請求等外部 API。
    task = asyncio.create_task(Collector.run(collector))
    _bg.add(task)
    task.add_done_callback(_bg.discard)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return html.render_settings()


@app.get("/api/holdings")
async def get_holdings():
    return JSONResponse(holdings.load())


@app.post("/api/holdings")
async def post_holdings(request: Request):
    if err := _token_error(request):
        return err
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"errors": {"_": "JSON 格式錯誤"}}, status_code=400)
    clean, errors = holdings.validate(payload)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    saved = holdings.save(clean)
    _run_in_background(_stocks)  # 立刻抓一次報價回填名稱
    return JSONResponse(saved)


@app.get("/api/snapshot")
async def get_snapshot():
    c = cache.get(_stocks.source)
    if not c:
        return JSONResponse({"fetched_at": None, "quote_date": None, "items": [], "errors": []})
    return JSONResponse(c["payload"])


@app.get("/settings/funds", response_class=HTMLResponse)
async def funds_page():
    return html.render_funds_settings()


@app.get("/api/funds")
async def get_funds():
    return JSONResponse(funds.load())


@app.post("/api/funds")
async def post_funds(request: Request):
    if err := _token_error(request):
        return err
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"errors": {"_": "JSON 格式錯誤"}}, status_code=400)
    clean, errors = funds.validate(payload)
    if errors:
        return JSONResponse({"errors": errors}, status_code=400)
    saved = funds.save(clean)
    _run_in_background(_funds)  # 立刻抓一次淨值
    return JSONResponse(saved)


@app.get("/api/funds/snapshot")
async def get_funds_snapshot():
    c = cache.get(_funds.source)
    if not c:
        return JSONResponse({"fetched_at": None, "fx": {}, "items": [], "errors": []})
    return JSONResponse(c["payload"])


@app.get("/api/funds/search")
async def search_funds(q: str = ""):
    q = q.strip()
    if not 2 <= len(q) <= 40:
        return JSONResponse({"error": "請輸入 2–40 個字"}, status_code=400)
    try:
        return JSONResponse(await funds_source.search(q))
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "基金資訊觀測站查詢失敗"}, status_code=502)


@app.get("/api/funds/lookup")
async def lookup_fund(site: str, code: str):
    if site not in funds.SITES or not funds.CODE_RE.fullmatch(code):
        return JSONResponse({"error": "參數錯誤"}, status_code=400)
    try:
        info = await funds_source.lookup(site, code)
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "基金資訊觀測站查詢失敗"}, status_code=502)
    if not info:
        return JSONResponse({"error": "查無此基金"}, status_code=404)
    return JSONResponse(info)


@app.get("/health")
async def health():
    sources = {}
    for c in COLLECTORS:
        cached = cache.get(c.source)
        age = cached["age_seconds"] if cached else None
        sources[c.source] = {
            "available": cached is not None,
            "age_seconds": age,
            "stale": age is None or age > 2 * c.interval_seconds,
        }
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
