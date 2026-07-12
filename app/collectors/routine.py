"""依本地時間與更新次數產生作息提醒。"""
from __future__ import annotations

from datetime import datetime

from .. import cache
from .base import Collector


def _period(now: datetime) -> tuple[str, str, str, str]:
    hour = now.hour
    if hour < 2 or hour >= 22:
        return "night", "sleep", "夜深了，該休息了", "停止熬夜，準備入睡。"
    if hour < 7:
        return "deep_night", "sleep", "凌晨了，請立即休息", "停止使用電腦，讓身體真正休息。"
    if hour < 9:
        return "breakfast", "breakfast", "早安，記得吃早餐", "補充水分與早餐，準備今天的工作。"
    if hour < 12:
        return "work_morning", "work", "", ""
    if hour < 13:
        return "lunch", "meal", "午餐時間", "離開電腦，好好吃飯並休息一下。"
    if hour < 18:
        return "work_afternoon", "work", "", ""
    if hour < 19:
        return "dinner", "meal", "晚餐時間提示", "放下手邊工作，按時吃晚餐。"
    return "work_evening", "work", "", ""


def build_payload(now: datetime, previous: dict | None) -> dict:
    segment, mode, title, message = _period(now)
    day = now.date().isoformat()
    if mode != "work":
        return {
            "day": day,
            "segment": segment,
            "mode": mode,
            "title": title,
            "message": message,
            "icon": "moon" if mode == "sleep" else mode,
            "cycle_step": 0,
            "remaining_updates": None,
        }

    same_cycle = bool(
        previous
        and previous.get("day") == day
        and previous.get("segment") == segment
    )
    step = int(previous.get("cycle_step", 0)) + 1 if same_cycle else 1
    step = 1 if step > 4 else step
    reminder = step == 4
    return {
        "day": day,
        "segment": segment,
        "mode": "break" if reminder else "focus",
        "title": "喝水與伸展時間" if reminder else "專注工作中",
        "message": (
            "離開電腦，喝水並活動筋骨 5 分鐘。"
            if reminder
            else f"再 {4 - step} 次更新後提醒喝水伸展。"
        ),
        "icon": "water" if reminder else "focus",
        "cycle_step": step,
        "remaining_updates": 0 if reminder else 4 - step,
    }


class RoutineCollector(Collector):
    source = "routine"
    interval_seconds = 600

    async def fetch(self) -> dict:
        cached = cache.get(self.source)
        previous = cached["payload"] if cached else None
        return build_payload(datetime.now(), previous)
