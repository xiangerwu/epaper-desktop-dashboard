from __future__ import annotations

import asyncio
import json
import subprocess
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

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
        self.assertRegex(page, r"Claude\s*<span class=\"age\">1 分前</span>")
        self.assertRegex(page, r"Codex\s*<span class=\"age\">2 小時前</span>")
        self.assertIn("頁面產生於", page)


if __name__ == "__main__":
    unittest.main()
