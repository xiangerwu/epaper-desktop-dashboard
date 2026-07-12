"""Periodic real-device contract: ADB screenshot must match the target panel."""
from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from app.device.adb import screencap


with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as target:
    path = Path(target.name)
try:
    image = Path(screencap(str(path))).read_bytes()
finally:
    path.unlink(missing_ok=True)

if image[:8] != b"\x89PNG\r\n\x1a\n":
    raise SystemExit("EVAL_FAIL screenshot is not PNG")
size = struct.unpack(">II", image[16:24])
if size != (1872, 1404):
    raise SystemExit(f"EVAL_FAIL expected 1872x1404, got {size[0]}x{size[1]}")
print("EVAL_OK device screenshot is 1872x1404 PNG")
