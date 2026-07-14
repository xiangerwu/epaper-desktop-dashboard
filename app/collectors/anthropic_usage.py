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
  - token 過期時的 refresh 由 CLAUDE_TOKEN_REFRESH 旗標控制(預設關)。
    * 關:過期就 raise,由 base 保留舊快取(dev PC 靠 Claude Code CLI 保鮮)。
    * 開:用 refreshToken 換新並「防禦性寫回」(重讀最新檔、只換必要欄位、原子替換),
      給無人值守、唯一持有憑證的機器(如派)自我維持用。詳見 _refresh_token。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..net import client
from .base import Collector

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# OAuth refresh(值對照 openusage ClaudeUsageClient.swift;client_id 為 Claude Code 公開識別碼)
REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
REFRESH_SCOPES = "user:profile user:inference user:sessions:claude_code user:mcp_servers user:file_upload"
# 剩餘效期低於此(毫秒)就提早換新,避免每輪都卡到期邊界
REFRESH_SKEW_MS = 5 * 60 * 1000


def _cred_path() -> Path:
    base = os.getenv("CLAUDE_CONFIG_DIR", "").strip() or str(Path.home() / ".claude")
    return Path(base) / ".credentials.json"


def _atomic_write(path: Path, obj: dict) -> None:
    """同目錄寫 temp 再 os.replace 原子替換;權限收斂到 600,失敗不留半殘檔。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # POSIX 生效;Windows 僅動唯讀位,無害
    except OSError:
        pass
    os.replace(tmp, path)


async def _refresh_token(cred: Path, oauth: dict) -> str:
    """用 refreshToken 換新 access token,防禦性寫回 .credentials.json,回傳新 token。

    寫回前重讀最新的檔(可能被互動 CLI 動過),只覆寫 claudeAiOauth 的
    accessToken/refreshToken/expiresAt,其餘欄位(scopes/subscriptionType/
    refreshTokenExpiresAt…)原樣保留。任一步失敗就 raise,由 base 保留舊快取。
    """
    body = {
        "grant_type": "refresh_token",
        "refresh_token": oauth["refreshToken"],
        "client_id": CLIENT_ID,
        "scope": REFRESH_SCOPES,
    }
    async with client(timeout=15.0) as c:
        r = await c.post(REFRESH_URL, json=body, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        resp = r.json()

    access = resp.get("access_token")
    if not access:
        raise RuntimeError("refresh 回應缺 access_token")

    latest = json.loads(cred.read_text(encoding="utf-8"))
    lo = latest.get("claudeAiOauth", {})
    lo["accessToken"] = access
    if resp.get("refresh_token"):  # refresh token 可能輪換
        lo["refreshToken"] = resp["refresh_token"]
    if resp.get("expires_in"):
        lo["expiresAt"] = int(time.time() * 1000 + resp["expires_in"] * 1000)
    latest["claudeAiOauth"] = lo
    _atomic_write(cred, latest)
    return access


async def _read_token() -> str:
    env = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    if env:
        return env
    cred = _cred_path()
    if not cred.exists():
        raise RuntimeError(f"找不到 {cred};設 CLAUDE_CODE_OAUTH_TOKEN 或提供 credentials")
    o = json.loads(cred.read_text(encoding="utf-8")).get("claudeAiOauth", {})
    tok = o.get("accessToken", "")
    if not tok:
        raise RuntimeError("credentials 內無 accessToken")

    exp = o.get("expiresAt", 0)
    now_ms = time.time() * 1000
    # 尚未接近到期:直接用
    if not exp or exp - now_ms > REFRESH_SKEW_MS:
        return tok
    # 接近或已過期
    if not settings.claude_token_refresh:
        if exp < now_ms:
            raise RuntimeError(
                "Claude access token 已過期(未開 CLAUDE_TOKEN_REFRESH;"
                "在有 Claude Code 登入處保鮮,或於派上設 CLAUDE_TOKEN_REFRESH=true)"
            )
        return tok  # 還沒過期,先用著,等旗標開了才會提早換
    rtok = o.get("refreshToken", "")
    if not rtok:
        raise RuntimeError("無 refreshToken,無法自動換新(請重新登入 Claude Code)")
    rexp = o.get("refreshTokenExpiresAt", 0)
    if rexp and rexp < now_ms:
        raise RuntimeError("refreshToken 也過期了,需在有 Claude Code 的機器重新登入")
    return await _refresh_token(cred, o)


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
        token = await _read_token()
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
