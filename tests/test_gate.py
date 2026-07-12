from __future__ import annotations

import asyncio
import json
import subprocess
import unittest
from datetime import datetime, timedelta
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
    def test_eight_time_boundaries(self) -> None:
        from app.collectors.routine import build_payload

        day = datetime(2026, 7, 13)
        boundaries = [
            ("01:59", "night", "02:00", "deep_night"),
            ("06:59", "deep_night", "07:00", "breakfast"),
            ("08:59", "breakfast", "09:00", "work_morning"),
            ("11:59", "work_morning", "12:00", "lunch"),
            ("12:59", "lunch", "13:00", "work_afternoon"),
            ("17:59", "work_afternoon", "18:00", "dinner"),
            ("18:59", "dinner", "19:00", "work_evening"),
            ("21:59", "work_evening", "22:00", "night"),
        ]
        for before, before_segment, at, at_segment in boundaries:
            with self.subTest(at=at):
                before_time = datetime.combine(day, datetime.strptime(before, "%H:%M").time())
                at_time = datetime.combine(day, datetime.strptime(at, "%H:%M").time())
                self.assertEqual(build_payload(before_time, None)["segment"], before_segment)
                self.assertEqual(build_payload(at_time, None)["segment"], at_segment)

    def test_nonwork_titles_and_icons(self) -> None:
        from app.collectors.routine import build_payload

        cases = [
            (0, "夜深了，該休息了", "moon"),
            (2, "凌晨了，請立即休息", "moon"),
            (7, "早安，記得吃早餐", "breakfast"),
            (12, "午餐時間", "meal"),
            (18, "晚餐時間提示", "meal"),
            (22, "夜深了，該休息了", "moon"),
        ]
        for hour, title, icon in cases:
            with self.subTest(hour=hour):
                payload = build_payload(datetime(2026, 7, 13, hour), None)
                self.assertEqual((payload["title"], payload["icon"]), (title, icon))
                self.assertEqual(payload["cycle_step"], 0)
                self.assertIsNone(payload["remaining_updates"])

    def test_work_cycle_wraps_every_four_updates(self) -> None:
        from app.collectors.routine import build_payload

        now = datetime(2026, 7, 13, 9)
        payloads = []
        previous = None
        for offset in range(5):
            previous = build_payload(now + timedelta(minutes=10 * offset), previous)
            payloads.append(previous)

        self.assertEqual([p["cycle_step"] for p in payloads], [1, 2, 3, 4, 1])
        self.assertEqual([p["remaining_updates"] for p in payloads], [3, 2, 1, 0, 3])
        self.assertEqual(
            [p["title"] for p in payloads],
            ["專注工作中", "專注工作中", "專注工作中", "喝水與伸展時間", "專注工作中"],
        )
        self.assertEqual([p["icon"] for p in payloads], ["focus", "focus", "focus", "water", "focus"])

    def test_work_cycle_resets_on_segment_or_day_change(self) -> None:
        from app.collectors.routine import build_payload

        morning = build_payload(datetime(2026, 7, 13, 9), None)
        morning = build_payload(datetime(2026, 7, 13, 9, 10), morning)
        afternoon = build_payload(datetime(2026, 7, 13, 13), morning)
        next_day = build_payload(datetime(2026, 7, 14, 13), afternoon)

        self.assertEqual(morning["cycle_step"], 2)
        self.assertEqual(afternoon["cycle_step"], 1)
        self.assertEqual(next_day["cycle_step"], 1)


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
        self.assertIn("頁面產生於", page)

    def test_routine_card_renders_without_apple_branding(self) -> None:
        from app.render import html, view

        cached = {
            "weather": None,
            "air_quality": None,
            "anthropic_usage": None,
            "codex_usage": None,
            "routine": {
                "payload": {
                    "mode": "work",
                    "segment": "work_morning",
                    "title": "專注工作中",
                    "message": "保持節奏",
                    "icon": "focus",
                    "cycle_step": 2,
                    "remaining_updates": 2,
                },
                "age_seconds": 0,
            },
        }
        with patch.object(view.cache, "get", side_effect=cached.get):
            page = html.render()

        self.assertIn('<section class="card routine">', page)
        self.assertIn('<div class="routine-icon">', page)
        self.assertIn("專注工作中", page)
        self.assertIn("保持節奏", page)
        self.assertNotIn("Apple", page)

    def test_nonwork_routine_hides_zero_cycle(self) -> None:
        from app.render import html, view

        cached = {
            "weather": None,
            "air_quality": None,
            "anthropic_usage": None,
            "codex_usage": None,
            "routine": {
                "payload": {
                    "title": "午餐時間",
                    "message": "好好吃飯",
                    "icon": "meal",
                    "cycle_step": 0,
                    "remaining_updates": None,
                },
                "age_seconds": 0,
            },
        }
        with patch.object(view.cache, "get", side_effect=cached.get):
            page = html.render()

        self.assertIn("午餐時間", page)
        self.assertNotIn("第 0 次", page)


if __name__ == "__main__":
    unittest.main()
