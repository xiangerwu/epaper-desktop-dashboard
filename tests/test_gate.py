from __future__ import annotations

import asyncio
import json
import subprocess
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import cache
from app.collectors.anthropic_usage import _reset_label as anthropic_reset_label
from app.collectors.base import Collector
from app.collectors.codex_usage import _reset_label as codex_reset_label
from app.device import adb


class ResetLabelTests(unittest.TestCase):
    def test_anthropic_iso_reset_uses_local_time(self) -> None:
        raw = "2026-01-02T03:04:00+00:00"
        expected = "重置 " + datetime.fromisoformat(raw).astimezone().strftime("%m/%d %H:%M")
        self.assertEqual(anthropic_reset_label(raw), expected)
        self.assertEqual(anthropic_reset_label("not-a-date"), "")
        self.assertEqual(anthropic_reset_label(None), "")

    def test_codex_epoch_reset_uses_local_time(self) -> None:
        epoch = 1_767_323_040
        expected = "重置 " + datetime.fromtimestamp(epoch).astimezone().strftime("%m/%d %H:%M")
        self.assertEqual(codex_reset_label(epoch), expected)
        self.assertEqual(codex_reset_label("not-an-epoch"), "")
        self.assertEqual(codex_reset_label(None), "")


class CacheFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_collector_keeps_last_successful_value(self) -> None:
        class FailingCollector(Collector):
            source = "test_source"

            async def fetch(self) -> dict:
                raise RuntimeError("offline")

        stale = {"payload": {"value": "last good"}, "updated_at": 1.0}
        with patch.object(cache, "put") as put, patch.object(
            cache, "get", return_value=stale
        ), self.assertLogs("collector", level="ERROR"):
            before = cache.get("test_source")
            await FailingCollector().run()
            after = cache.get("test_source")

        put.assert_not_called()
        self.assertIs(after, before)


class AdbErrorTests(unittest.TestCase):
    @patch.object(adb, "_base", return_value=["adb"])
    @patch.object(adb.subprocess, "run")
    def test_nonzero_exit_is_an_adb_error(self, run, _base) -> None:
        run.return_value = subprocess.CompletedProcess(
            ["adb", "devices"], 1, stdout=b"", stderr=b"device offline"
        )
        with self.assertRaisesRegex(adb.AdbError, "device offline"):
            adb._run(["devices"])

    @patch.object(adb, "_base", return_value=["adb"])
    @patch.object(adb.subprocess, "run", side_effect=subprocess.TimeoutExpired("adb", 30))
    def test_timeout_is_an_adb_error(self, _run, _base) -> None:
        with self.assertRaisesRegex(adb.AdbError, "逾時"):
            adb._run(["devices"])

    def test_devices_propagates_common_runner_error(self) -> None:
        with patch.object(adb, "_run", side_effect=adb.AdbError("cannot execute")):
            with self.assertRaisesRegex(adb.AdbError, "cannot execute"):
                adb.devices()

    def test_connect_reconnects_when_offline(self) -> None:
        # WiFi target 先 offline,connect() 應先 disconnect 清 stale 再重連成功。
        calls: list[str] = []
        states = iter(["offline", "device"])  # 重連後轉 device

        def fake_run(args, *, binary=False, target=True):
            calls.append(args[0])
            if args[0] == "devices":
                return f"List of devices attached\n1.2.3.4:5555   {next(states)} product:x\n"
            return "ok"

        with patch.object(adb, "TARGET", "1.2.3.4:5555"), patch.object(
            adb, "_run", side_effect=fake_run
        ):
            adb.connect()  # 不應 raise

        self.assertIn("disconnect", calls)
        self.assertIn("connect", calls)
        self.assertLess(calls.index("disconnect"), calls.index("connect"))

    def test_connect_raises_when_still_offline(self) -> None:
        def fake_run(args, *, binary=False, target=True):
            if args[0] == "devices":
                return "List of devices attached\n1.2.3.4:5555   offline\n"
            return "ok"

        with patch.object(adb, "TARGET", "1.2.3.4:5555"), patch.object(
            adb, "_run", side_effect=fake_run
        ):
            with self.assertRaises(adb.AdbError):
                adb.connect()


class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_reports_age_and_stale_at_twice_interval(self) -> None:
        from app import main

        collectors = [
            SimpleNamespace(source="fresh", interval_seconds=600),
            SimpleNamespace(source="old", interval_seconds=600),
            SimpleNamespace(source="missing", interval_seconds=600),
        ]
        cached = {
            "fresh": {"age_seconds": 1_200},
            "old": {"age_seconds": 1_201},
            "missing": None,
        }
        with patch.object(main, "COLLECTORS", collectors), patch.object(
            main.cache, "get", side_effect=cached.get
        ):
            response = await main.health()

        body = json.loads(response.body)
        self.assertTrue(body["ok"])
        self.assertEqual(
            body["sources"],
            {
                "fresh": {"available": True, "age_seconds": 1_200, "stale": False},
                "old": {"available": True, "age_seconds": 1_201, "stale": True},
                "missing": {"available": False, "age_seconds": None, "stale": True},
            },
        )


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_collectors_start_concurrently_and_openrouter_stays_disabled(self) -> None:
        from app import main
        from app.collectors import COLLECTORS

        self.assertNotIn("openrouter", {collector.source for collector in COLLECTORS})
        events = []

        class StubCollector:
            def __init__(self, source: str) -> None:
                self.source = source

            async def run(self) -> None:
                events.append(f"{self.source}-start")
                await asyncio.sleep(0)
                events.append(f"{self.source}-end")

        collectors = [StubCollector("one"), StubCollector("two")]
        with patch.object(main, "COLLECTORS", collectors), patch.object(
            main.scheduler, "start"
        ), patch.object(main.scheduler, "shutdown"):
            async with main.lifespan(main.app):
                pass

        self.assertEqual(events[:2], ["one-start", "two-start"])


class SchedulerTests(unittest.TestCase):
    def test_slow_sources_run_hourly_and_others_start_active(self) -> None:
        from app import scheduler

        async def run() -> None:
            pass

        collectors = [
            SimpleNamespace(source="weather", interval_seconds=3_600, cron_minute=0, run=run),
            SimpleNamespace(source="air_quality", interval_seconds=3_600, cron_minute=0, run=run),
            SimpleNamespace(source="anthropic_usage", interval_seconds=600, cron_minute=None, run=run),
            SimpleNamespace(source="codex_usage", interval_seconds=600, cron_minute=None, run=run),
            SimpleNamespace(source="routine", interval_seconds=600, cron_minute=None, run=run),
        ]
        fake_scheduler = MagicMock()
        with patch.object(scheduler, "COLLECTORS", collectors), patch.object(
            scheduler, "_sched", fake_scheduler
        ), patch.object(scheduler, "settings", SimpleNamespace(refresh_via_adb=False)):
            scheduler.start()

        jobs = {
            call.kwargs["id"]: (call.args[1], call.kwargs)
            for call in fake_scheduler.add_job.call_args_list
        }
        for source in ("weather", "air_quality"):
            self.assertEqual(jobs[source][0], "cron")
            self.assertEqual(jobs[source][1]["minute"], 0)
        for source in ("anthropic_usage", "codex_usage", "routine"):
            self.assertEqual(jobs[source][0], "interval")
            self.assertEqual(jobs[source][1]["seconds"], 600)
        self.assertTrue(all("next_run_time" not in kwargs for _, kwargs in jobs.values()))


class RoutineTests(unittest.TestCase):
    def test_longest_prompt_matches_dashboard_font_baseline(self) -> None:
        from app.collectors.routine import FILLERS, QUIPS

        prompts = [item[2] for item in QUIPS] + [item[1] for item in FILLERS]
        self.assertEqual(max(map(len, prompts)), 21)

    def test_quip_shows_anchor_soon_after_time(self) -> None:
        from app.collectors.routine import build_payload

        # 到某時段錨點後 GRACE_MIN(20)分內,顯示該時段語錄。
        cases = [
            (8, 35, "🌅", "教授就要改你這個人了"),   # 08:30 + 5 分
            (9, 30, "🌅", "文獻就追不上我"),          # 剛好 09:30
            (14, 5, "☕", "喝杯咖啡"),                # 14:00 + 5 分
            (23, 40, "🌙", "先跟自己和解"),           # 23:30 + 10 分
        ]
        for hour, minute, emoji, fragment in cases:
            with self.subTest(at=f"{hour:02d}:{minute:02d}"):
                payload = build_payload(datetime(2026, 7, 13, hour, minute))
                self.assertEqual(payload["emoji"], emoji)
                self.assertIn(fragment, payload["message"])
                self.assertEqual(payload["cycle_step"], 0)
                self.assertIsNone(payload["remaining_updates"])

    def test_quip_shows_random_filler_in_gap(self) -> None:
        from app.collectors.routine import FILLERS, build_payload

        filler_texts = {text for _, text in FILLERS}
        filler_emojis = {emoji for emoji, _ in FILLERS}
        # 13:00 距 12:30 錨點 30 分 > 20,進入空檔 → 隨機提示。
        p1 = build_payload(datetime(2026, 7, 13, 13, 0))
        p2 = build_payload(datetime(2026, 7, 13, 13, 5))   # 同一 10 分桶
        self.assertIn(p1["message"], filler_texts)
        self.assertIn(p1["emoji"], filler_emojis)
        self.assertEqual(p1, p2)   # 同桶穩定,重載不變


class RefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_runs_routine_once_and_redirects(self) -> None:
        from app import main

        class CountingRoutine:
            source = "routine"

            def __init__(self) -> None:
                self.count = 0

            async def run(self) -> None:
                self.count += 1

        routine = CountingRoutine()
        with patch.object(main, "COLLECTORS", [routine]):
            response = await main.refresh_now()

        self.assertEqual(routine.count, 1)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")


class DashboardAgeTests(unittest.TestCase):
    def test_ai_cache_ages_are_compact_and_rendered(self) -> None:
        from app.render import html, view

        cached = {
            "weather": None,
            "anthropic_usage": {"payload": {"lines": []}, "age_seconds": 61},
            "codex_usage": {"payload": {"lines": []}, "age_seconds": 7_201},
        }
        with patch.object(view.cache, "get", side_effect=cached.get):
            model = view.build()
            page = html.render()

        self.assertEqual([column["age"] for column in model["ai_columns"]], ["1 分前", "2 小時前"])
        self.assertRegex(page, r"Claude</span>\s*<span class=\"age\">1 分前</span>")
        self.assertRegex(page, r"Codex</span>\s*<span class=\"age\">2 小時前</span>")
        self.assertIn("頁面更新於", page)

    def test_routine_card_renders(self) -> None:
        from app.render import html, view

        cached = {
            "weather": None,
            "air_quality": None,
            "anthropic_usage": None,
            "codex_usage": None,
            "routine": {
                "payload": {
                    "emoji": "🌅",
                    "message": "只要我醒得夠快,文獻就追不上我。",
                    "cycle_step": 0,
                    "remaining_updates": None,
                },
                "age_seconds": 0,
            },
        }
        with patch.object(view.cache, "get", side_effect=cached.get):
            page = html.render()

        self.assertIn('<section class="card routine">', page)
        self.assertIn('<div class="routine-icon">', page)
        self.assertIn("🌅", page)
        self.assertIn("文獻就追不上我", page)
        # 番茄鐘三段版面:上層語錄 / 中番茄鐘 / 下保留空塊
        self.assertIn('class="pomodoro"', page)
        self.assertIn('class="routine-extra"', page)
        self.assertIn('id="petSprite"', page)
        self.assertIn('id="petDialogue"', page)
        self.assertIn("var PET_DIALOGUES", page)
        self.assertIn("paintDialogue()", page)
        self.assertIn("/pet/spritesheet.webp", page)
        self.assertIn('setPet(seg < 4 ? "focus" : "break")', page)
        self.assertIn('class="pomo-message" id="pomoMessage"', page)
        self.assertIn('<span id="pomoRemain"></span> · <span id="pomoStage"></span>', page)
        self.assertIn("justify-content:flex-start", page)
        self.assertIn("messageEl.textContent = MAIN[seg]", page)
        self.assertIn('stageEl.textContent = "第 "', page)
        self.assertIn("font-size:3.5vmin", page)
        self.assertIn("font-size:calc(2.8vmin + 2pt)", page)
        self.assertIn("border:0.35vmin solid var(--ink)", page)
        self.assertIn(".pet-dialogue::before", page)

    def test_routine_card_shows_quip_without_cycle_meta(self) -> None:
        from app.render import html, view

        cached = {
            "weather": None,
            "air_quality": None,
            "anthropic_usage": None,
            "codex_usage": None,
            "routine": {
                "payload": {
                    "emoji": "🌙",
                    "message": "放過跑不出的數據,今晚先跟自己和解。",
                    "cycle_step": 0,
                    "remaining_updates": None,
                },
                "age_seconds": 0,
            },
        }
        with patch.object(view.cache, "get", side_effect=cached.get):
            page = html.render()

        self.assertIn("今晚先跟自己和解", page)
        self.assertNotIn("第 0 次", page)


if __name__ == "__main__":
    unittest.main()
