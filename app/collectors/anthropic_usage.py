"""Claude 訂閱額度: GET https://api.anthropic.com/api/oauth/usage

做法參考 openusage(docs/providers/claude.md)。用 Claude Code 登入的 OAuth token
(非 API key),讀訂閱的 5 小時 / 7 天用量百分比。

token 來源優先序:
  1. CLAUDE_CODE_OAUTH_TOKEN 環境變數
  2. $CLAUDE_CONFIG_DIR/.credentials.json 或 ~/.claude/.credentials.json
     → claudeAiOauth.accessToken

注意:
  - `claude setup-token` 的 token 缺 user:profile scope,讀不到訂閱額度。
    需實際登入的 credentials。
  - token 過期不在此自動 refresh(refresh 會輪換 token,寫回失誤會弄壞 Claude Code
    登入)。過期就 raise,由 base 保留舊快取。PC 上 Claude Code 會自動保鮮。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from ..net import client
from .base import Collector

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"


def _read_token() -> str:
    env = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env:
        return env
    base = os.getenv("CLAUDE_CONFIG_DIR", "").strip() or str(Path.home() / ".claude")
    cred = Path(base) / ".credentials.json"
    if not cred.exists():
        raise RuntimeError(f"找不到 {cred};設 CLAUDE_CODE_OAUTH_TOKEN 或提供 credentials")
    o = json.loads(cred.read_text(encoding="utf-8")).get("claudeAiOauth", {})
    exp = o.get("expiresAt", 0)
    if exp and exp < time.time() * 1000:
        raise RuntimeError("Claude access token 已過期(需在有 Claude Code 登入處保鮮)")
    tok = o.get("accessToken", "")
    if not tok:
        raise RuntimeError("credentials 內無 accessToken")
    return tok


def _reset_label(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso).astimezone()  # 轉本地時區
    except ValueError:
        return ""
    return "重置 " + dt.strftime("%m/%d %H:%M")


class AnthropicUsageCollector(Collector):
    source = "anthropic_usage"
    interval_seconds = 600  # 10 分

    async def fetch(self) -> dict:
        token = _read_token()
        async with client() as c:
            r = await c.get(USAGE_URL, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            data = r.json()

        lines = []
        for key, label in (("five_hour", "5 小時用量"), ("seven_day", "7 日內用量")):
            b = data.get(key)
            if b and b.get("utilization") is not None:
                lines.append({
                    "label": label,
                    "pct": round(b["utilization"]),
                    "detail": _reset_label(b.get("resets_at")),
                })
        return {"lines": lines}
