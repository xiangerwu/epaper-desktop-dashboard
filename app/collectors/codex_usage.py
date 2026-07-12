"""Codex(OpenAI Codex CLI)額度: GET https://chatgpt.com/backend-api/wham/usage

參考 openusage(docs/providers/codex.md)。用 Codex CLI 登入的 OAuth token,
讀 session/weekly 的 used_percent。

token 來源:$CODEX_HOME(預設 ~/.codex)/auth.json
  → tokens.access_token(或頂層 access_token)

注意:回應欄位結構待實際憑證接上後校準(現在無憑證可測)。解析寫得防禦性,
抓不到就 raise,由 base 保留舊快取 / 顯示「待憑證」。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from ..net import client
from .base import Collector

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


def _read_token() -> str:
    env = os.getenv("CODEX_ACCESS_TOKEN", "").strip()
    if env:
        return env
    base = os.getenv("CODEX_HOME", "").strip() or str(Path.home() / ".codex")
    auth = Path(base) / "auth.json"
    if not auth.exists():
        raise RuntimeError(f"找不到 {auth};請先用 Codex CLI 登入(codex)")
    d = json.loads(auth.read_text(encoding="utf-8"))
    tok = (d.get("tokens") or {}).get("access_token") or d.get("access_token", "")
    if not tok:
        raise RuntimeError("auth.json 內無 access_token")
    return tok


def _reset_label(epoch: float | None) -> str:
    """reset_at 是 Unix epoch 秒。"""
    if not epoch:
        return ""
    try:
        return "重置 " + datetime.fromtimestamp(epoch).astimezone().strftime("%m/%d %H:%M")
    except (ValueError, TypeError, OSError):
        return ""


def _window_label(seconds: int | None) -> str:
    """依窗口長度(秒)標籤,不靠 primary/secondary 位置(API 會換位置)。"""
    if seconds == 18000:
        return "5 小時用量"
    if seconds == 604800:
        return "7 日內用量"
    if not seconds:
        return "用量"
    hours = seconds / 3600
    if hours < 48:
        return f"{round(hours)} 小時用量"
    return f"{round(hours / 24)} 日內用量"


class CodexUsageCollector(Collector):
    source = "codex_usage"
    interval_seconds = 600  # 10 分

    async def fetch(self) -> dict:
        token = _read_token()
        async with client() as c:
            r = await c.get(USAGE_URL, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()

        # rate_limit 內含數個窗口;API 會把 5小時/7日 換到 primary/secondary,
        # 故依各窗口的 limit_window_seconds 標籤,不靠位置。
        rl = data.get("rate_limit") or {}
        wins = [rl.get("primary_window"), rl.get("secondary_window")]
        extra = data.get("additional_rate_limits")
        if isinstance(extra, list):
            wins += extra

        seen: set = set()
        rows = []
        for win in wins:
            if not win or win.get("used_percent") is None:
                continue
            secs = win.get("limit_window_seconds")
            if secs in seen:
                continue
            seen.add(secs)
            rows.append((secs if secs is not None else 1 << 62, {
                "label": _window_label(secs),
                "pct": round(win["used_percent"]),
                "detail": _reset_label(win.get("reset_at")),
            }))
        rows.sort(key=lambda r: r[0])  # 短窗口(5小時)在前,長窗口(7日)在後
        return {"lines": [row for _, row in rows]}
