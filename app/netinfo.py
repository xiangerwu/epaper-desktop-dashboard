"""本機 LAN IP 探測。給桌面 App 顯示可分享給裝置的看板網址用。"""
from __future__ import annotations

import socket


def lan_ip() -> str:
    """回本機對外網段的 IP;無網路時回 127.0.0.1。

    連 8.8.8.8:80 但走 UDP,不會真的送封包,只是讓 OS 挑出對外介面,
    再從 socket 讀回本機那端的位址。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
