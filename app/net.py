"""共用 httpx 設定。

Python 3.14 預設開 VERIFY_X509_STRICT,某些政府/公開 API(如 CWA)的憑證
缺 Subject Key Identifier 會被擋。這裡放寬「僅」該項嚴格檢查,CA 信任鏈仍正常驗證。
"""
from __future__ import annotations

import ssl

import httpx


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    # 保留 CA 驗證,只關掉過嚴的 RFC5280 strict(SKI 等擴充強制)
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout, verify=_ssl_context())
