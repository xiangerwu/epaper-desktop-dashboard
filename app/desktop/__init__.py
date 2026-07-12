"""桌面背景 App:系統匣常駐 + 可叫出的看板預覽視窗。

服務(uvicorn)在背景執行緒跑;pywebview 視窗在主執行緒;pystray 系統匣在另一
執行緒。關閉視窗只隱藏,真正結束要用系統匣選單。啟動:`python -m app.desktop`。
"""
from __future__ import annotations

import logging
import threading
import time
import webbrowser

import uvicorn

from .. import netinfo
from ..config import settings
from ..main import app, _choose_port

log = logging.getLogger("desktop")

APP_TITLE = "Pi 電子紙看板"


def _tray_image(port: int):
    """畫一張簡單的系統匣圖示(黑底白框 + 溫度感的圓點),不依賴字型。"""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGB", (size, size), "#18181b")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([8, 8, size - 8, size - 8], radius=10, outline="#ffffff", width=4)
    d.ellipse([24, 24, 40, 40], fill="#ffffff")
    return img


def main() -> None:
    import pystray
    import webview

    port = _choose_port()
    ip = netinfo.lan_ip()
    share_url = f"http://{ip}:{port}/"
    preview_url = f"http://127.0.0.1:{port}/app"

    # 1) 背景執行緒起服務
    server = uvicorn.Server(uvicorn.Config(app, host=settings.host, port=port, log_level="info"))
    threading.Thread(target=server.run, daemon=True, name="uvicorn").start()

    for _ in range(100):  # 最多等 ~10s 服務就緒
        if server.started:
            break
        time.sleep(0.1)
    else:
        log.warning("服務逾時未就緒,仍繼續開視窗")

    log.info("desktop app 就緒:預覽 %s,分享 %s", preview_url, share_url)

    # 2) 主執行緒的預覽視窗;關窗只隱藏,結束才真的 destroy
    window = webview.create_window(APP_TITLE, preview_url, width=1180, height=760)
    state = {"quitting": False}

    def _on_closing():
        if state["quitting"]:
            return True  # 允許關閉(來自系統匣「結束」)
        window.hide()
        return False  # 攔下使用者關窗,只隱藏

    window.events.closing += _on_closing

    # 3) 系統匣圖示(獨立執行緒)
    def _show(icon, item):
        window.show()

    def _open_browser(icon, item):
        webbrowser.open(share_url)

    def _quit(icon, item):
        state["quitting"] = True
        server.should_exit = True
        icon.stop()
        window.destroy()

    icon = pystray.Icon(
        "pi-eink-dashboard",
        _tray_image(port),
        APP_TITLE,
        menu=pystray.Menu(
            pystray.MenuItem("顯示預覽", _show, default=True),
            pystray.MenuItem("用瀏覽器開啟看板", _open_browser),
            pystray.MenuItem(f"{ip}:{port}", None, enabled=False),
            pystray.MenuItem("結束", _quit),
        ),
    )
    threading.Thread(target=icon.run, daemon=True, name="tray").start()

    # 阻塞在主執行緒;window.destroy() 後才返回
    webview.start()

    server.should_exit = True
    log.info("desktop app 結束")
