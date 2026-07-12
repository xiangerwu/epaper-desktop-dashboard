"""每個資料源存「最後一次成功」的 JSON + 時間戳。

單一 API 失敗時,渲染層讀舊值續畫,不讓畫面空白。
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from .config import CACHE_DB


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(CACHE_DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        " source TEXT PRIMARY KEY,"
        " payload TEXT NOT NULL,"
        " updated_at REAL NOT NULL)"
    )
    return c


def put(source: str, payload: Any) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO cache(source, payload, updated_at) VALUES(?,?,?)"
            " ON CONFLICT(source) DO UPDATE SET payload=excluded.payload,"
            " updated_at=excluded.updated_at",
            (source, json.dumps(payload, ensure_ascii=False), time.time()),
        )


def get(source: str) -> Optional[dict]:
    """回傳 {'payload':..., 'updated_at':float, 'age_seconds':int} 或 None。"""
    with _conn() as c:
        row = c.execute(
            "SELECT payload, updated_at FROM cache WHERE source=?", (source,)
        ).fetchone()
    if not row:
        return None
    payload, updated_at = row
    return {
        "payload": json.loads(payload),
        "updated_at": updated_at,
        "age_seconds": int(time.time() - updated_at),
    }
