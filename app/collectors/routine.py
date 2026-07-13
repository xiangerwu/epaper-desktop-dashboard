"""依本地時間顯示一句時段語錄(早上幽默、下午打氣、晚上療癒);空檔輪換隨機提示。"""
from __future__ import annotations

import random
from datetime import datetime

from .base import Collector

# 時段語錄錨點:(分鐘, emoji, 句子),依分鐘遞增排列。
# 查表規則:取「時間 <= 現在」的最後一則;都不符(00:00 之前)就輪回最後一則(前一晚)。
QUIPS: list[tuple[int, str, str]] = [
    (1 * 60 +  0, "🌙", "閉上眼,夢裡什麼都有,包括順利畢業。"),
    (3 * 60 +  0, "🌙", "還醒著也沒關係,喝口水、關掉螢幕,先躺平。"),
    (7 * 60 +  0, "🌅", "早安,先喝一口水,今天不用完美,只要開始。"),
    (8 * 60 + 30, "🌅", "今天再不改進度,教授就要改你這個人了。"),
    (9 * 60 + 30, "🌅", "只要我醒得夠快,文獻就追不上我。"),
    (10 * 60 + 30, "🌅", "打開 Word,今天至少生出一個標點符號!"),
    (11 * 60 + 30, "🌅", "中午前再擠一句,寫爛沒關係,先有字再說。"),
    (12 * 60 + 30, "☕", "先去吃飯,餓著肚子跟論文拚沒有勝算。"),
    (14 * 60 +  0, "☕", "跑不出數據沒關係,我們先去喝杯咖啡。"),
    (15 * 60 + 30, "☕", "論文本來就是垃圾,不要對自己太苛刻。"),
    (16 * 60 + 30, "☕", "別哭,修改意見再多,我們一條一條過。"),
    (17 * 60 + 30, "☕", "今天看懂了三篇文獻,你已經超級棒了。"),
    (18 * 60 + 30, "🌙", "晚餐時間,先離開座位把自己餵飽。"),
    (19 * 60 + 30, "🌙", "晚上這段慢慢來,做一點點就算數。"),
    (21 * 60 +  0, "🌙", "今天的文獻查完了,把筆電蓋上休息吧。"),
    (22 * 60 +  0, "🌙", "教授也睡了,你現在焦慮他也看不到。"),
    (23 * 60 + 30, "🌙", "放過跑不出的數據,今晚先跟自己和解。"),
]


# 時段語錄之間的空檔輪換提示:(emoji, 句子)。
FILLERS: list[tuple[str, str]] = [
    ("🍵", "起來動一動,喝口水。"),
    ("🌿", "抬頭看看遠方,讓眼睛休息一下。"),
    ("🎧", "放首歌,回到自己的節奏。"),
    ("🧩", "卡住就先跳下一題,別硬耗。"),
    ("📌", "記得存檔,別讓努力白費。"),
    ("🪑", "調整一下坐姿,肩膀放鬆。"),
    ("🌤", "進度慢也是進度,別急。"),
    ("⏳", "一步一步來,總會到的。"),
    ("🫖", "泡杯茶,獎勵一下自己。"),
    ("📝", "把腦中的想法先寫下來。"),
]

# 到某個時段錨點後,先顯示該語錄這麼久(分),之後空檔才輪換隨機提示。
GRACE_MIN = 20


def _select(now: datetime) -> tuple[str, str]:
    """到點 GRACE_MIN 分內顯示該時段語錄;空檔則依 10 分桶輪換隨機提示。"""
    mod = now.hour * 60 + now.minute
    anchor = QUIPS[-1]        # 00:00~第一個錨點前 → 輪回前一晚最後一則
    anchor_min = anchor[0] - 24 * 60
    for a_min, emoji, text in QUIPS:
        if a_min <= mod:
            anchor, anchor_min = (a_min, emoji, text), a_min
    if mod - anchor_min < GRACE_MIN:
        return anchor[1], anchor[2]
    # 空檔:以「日期 + 10 分桶」為種子,同桶穩定、跨桶輪換、每天不同。
    seed = int(now.strftime("%Y%m%d")) * 200 + mod // 10
    return random.Random(seed).choice(FILLERS)


def build_payload(now: datetime, previous: dict | None = None) -> dict:
    emoji, message = _select(now)
    return {
        "day": now.date().isoformat(),
        "emoji": emoji,
        "message": message,
        # 保留給模板/其他測試的相容欄位(番茄鐘另負責工作節奏)。
        "cycle_step": 0,
        "remaining_updates": None,
    }


class RoutineCollector(Collector):
    source = "routine"
    interval_seconds = 600

    async def fetch(self) -> dict:
        return build_payload(datetime.now())
