"""集中設定。從 .env 讀,缺值時給安全預設。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# 目標裝置: HyRead Gaze Note Plus, 7.8" 直向 1404x1872。
# 直接吐 HTML 給裝置瀏覽器顯示,不產圖,故版面用相對單位自適應 viewport。
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CACHE_DB = DATA_DIR / "cache.sqlite"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() == "true"


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = _int("PORT", 8000)
    # 主埠被占用時依序嘗試的備用埠
    fallback_ports: tuple = tuple(
        int(x) for x in os.getenv("FALLBACK_PORTS", "8080,8888").split(",") if x.strip().isdigit()
    )

    # 頁面內建 meta 自動刷新秒數;0 = 關(改由 ADB 控刷新時設 0)
    html_auto_refresh_seconds: int = _int("HTML_AUTO_REFRESH_SECONDS", 600)

    # --- 天氣: CWA ---
    cwa_api_key: str = os.getenv("CWA_API_KEY", "")
    cwa_location: str = os.getenv("CWA_LOCATION", "臺中市")

    # --- AI 額度 ---
    # Claude 走 ~/.claude/.credentials.json 的 oauth token;Codex 走 ~/.codex/auth.json。
    # 兩者不吃 API key,見對應 collector。OpenRouter 才需自填金鑰:
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

    # --- ADB 刷新控制 ---
    refresh_via_adb: bool = _bool("REFRESH_VIA_ADB", False)
    # ADB 定時刷新裝置的間隔秒數
    adb_refresh_seconds: int = _int("ADB_REFRESH_SECONDS", 600)


settings = Settings()
