"""view-model → HTML 字串。直接吐給裝置瀏覽器,不產圖。"""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import ROOT
from . import view

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _pet_dialogues() -> dict[str, list[str]]:
    try:
        data = json.loads((ROOT / "pet" / "dialogue.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        state: [line for line in item.get("lines", []) if isinstance(line, str) and line]
        for state, item in data.items()
        if isinstance(state, str) and not state.startswith("_")
        and isinstance(item, dict) and isinstance(item.get("lines"), list)
    }


def render(auto_refresh_seconds: int = 0) -> str:
    ctx = view.build()
    ctx["auto_refresh_seconds"] = auto_refresh_seconds
    ctx["pet_dialogues"] = _pet_dialogues()
    return _env.get_template("dashboard.html.j2").render(**ctx)


def render_app_preview(share_url: str, ip: str, port: int) -> str:
    """桌面 App 預覽頁:頂列顯示 LAN IP 與看板網址,主體內嵌 `/` 即時看板。"""
    return _env.get_template("app_preview.html.j2").render(
        share_url=share_url, ip=ip, port=port,
    )
