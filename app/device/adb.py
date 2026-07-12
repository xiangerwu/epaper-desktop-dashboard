"""透過 ADB 控制 HyRead Gaze Note Plus(開放 Android 11)刷新看板。

顯示採 live HTML:裝置瀏覽器(或 kiosk App)開 DASHBOARD_URL。
ADB 的角色是「控制刷新」——喚醒螢幕、叫它重載頁面、觸發 e-ink full refresh。

連線:
  - WiFi:  ADB_TARGET=192.168.x.x:5555 (需先在裝置 `adb tcpip 5555` 開過一次)
  - USB:   ADB_TARGET 留空(接第一台)或填 USB serial

重載機制:重新丟同一個 VIEW intent,多數瀏覽器/ kiosk App 會重載頁面。
e-ink full refresh 是裝置特有——若知道 HyRead 的廣播 action,填 DEVICE_REFRESH_BROADCAST。

CLI:
  python -m app.device.adb devices
  python -m app.device.adb connect
  python -m app.device.adb open        # 首次:全螢幕開看板 URL
  python -m app.device.adb refresh     # 喚醒 + 重載 + (選)full refresh
  python -m app.device.adb screencap out.png
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys

from ..config import ROOT  # 匯入即觸發 load_dotenv,確保直接跑 CLI 也讀得到 .env

_ = ROOT  # 僅為載入副作用

ADB = os.getenv("ADB_BINARY", "adb")
TARGET = os.getenv("ADB_TARGET", "").strip()
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8000/").strip()
# 指定瀏覽器/kiosk App component, 例 de.ozerov.fully/.MainActivity;留空用系統預設
BROWSER_COMPONENT = os.getenv("DEVICE_BROWSER_COMPONENT", "").strip()
# e-ink full refresh 的廣播 action(裝置特有,接上裝置後確認);留空跳過
REFRESH_BROADCAST = os.getenv("DEVICE_REFRESH_BROADCAST", "").strip()

log = logging.getLogger("adb")


class AdbError(RuntimeError):
    pass


def _ensure_adb() -> str:
    path = shutil.which(ADB)
    if not path:
        raise AdbError(
            f"找不到 adb('{ADB}')。Pi: sudo apt install adb;"
            " Windows: 裝 platform-tools 並加進 PATH。"
        )
    return path


def _base(*, target: bool = True) -> list[str]:
    cmd = [_ensure_adb()]
    if target and TARGET:
        cmd += ["-s", TARGET]
    return cmd


def _run(
    args: list[str], *, binary: bool = False, target: bool = True
) -> bytes | str:
    try:
        proc = subprocess.run(
            _base(target=target) + args, capture_output=True, timeout=30
        )
    except subprocess.TimeoutExpired as e:
        raise AdbError(f"adb {' '.join(args)} 逾時 (30 秒)") from e
    except OSError as e:
        raise AdbError(f"adb {' '.join(args)} 無法執行: {e}") from e
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise AdbError(
            f"adb {' '.join(args)} 失敗 (rc={proc.returncode})"
            f"{f': {detail}' if detail else ''}"
        )
    return proc.stdout if binary else proc.stdout.decode(errors="replace")


def connect() -> str:
    if ":" in TARGET:  # WiFi
        msg = str(_run(["connect", TARGET], target=False)).strip()
        if "connected" not in msg and "already" not in msg:
            raise AdbError(f"adb connect {TARGET} 失敗: {msg}")
        return msg
    return devices()


def devices() -> str:
    return str(_run(["devices", "-l"], target=False)).strip()


def wake() -> None:
    """喚醒螢幕。多數 e-reader 無鎖屏,WAKEUP 即可。"""
    _run(["shell", "input", "keyevent", "KEYCODE_WAKEUP"])


def open_dashboard() -> None:
    """全螢幕開看板 URL。指定 component 最穩,否則交系統預設瀏覽器。"""
    args = ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", DASHBOARD_URL]
    if BROWSER_COMPONENT:
        args += ["-n", BROWSER_COMPONENT]
    _run(args)


def full_refresh() -> None:
    """觸發 e-ink 整頁刷新清殘影(裝置特有廣播;未設定就跳過)。"""
    if REFRESH_BROADCAST:
        _run(["shell", "am", "broadcast", "-a", REFRESH_BROADCAST])


def refresh() -> None:
    """定時呼叫: 喚醒 + 重載頁面 + (選) full refresh。

    ADB 連不上時只記警告不 raise,讓服務其餘部分照常。
    """
    try:
        if ":" in TARGET:
            connect()
        wake()
        open_dashboard()  # 重丟同 URL intent = 重載
        full_refresh()
    except AdbError as e:
        log.warning("refresh 略過: %s", e)


def screencap(local: str) -> str:
    """抓裝置目前畫面回來驗證。"""
    png = _run(["exec-out", "screencap", "-p"], binary=True)
    with open(local, "wb") as f:
        f.write(png)  # type: ignore[arg-type]
    return local


_COMMANDS = {
    "devices": lambda a: print(devices()),
    "connect": lambda a: print(connect()),
    "wake": lambda a: wake(),
    "open": lambda a: open_dashboard(),
    "refresh": lambda a: refresh(),
    "screencap": lambda a: print(screencap(a[0] if a else "screen.png")),
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in _COMMANDS:
        print(f"用法: python -m app.device.adb <{'|'.join(_COMMANDS)}>")
        return 2
    try:
        _COMMANDS[argv[0]](argv[1:])
        return 0
    except AdbError as e:
        print(f"[adb] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
