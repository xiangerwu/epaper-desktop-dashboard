from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import funds
from app.collectors.funds import parse_bot_csv, parse_five_dates

MINUS = "−"


def _cfg(*rows, enabled=True) -> dict:
    return {"funds": [{"isin": i, "name": n, "currency": c, "units": u, "cost_twd": k}
                      for i, n, c, u, k in rows],
            "display": {"enabled": enabled}}


def _snap(*items, fx=None) -> dict:
    return {"fx": fx or {}, "items": [
        {"isin": i, "nav": n, "prev_nav": p, "nav_date": d} for i, n, p, d in items]}


class ValidateTests(unittest.TestCase):
    def test_accepts_spec_example_without_fundclear_code(self) -> None:
        clean, errors = funds.validate({"funds": [
            {"isin": "TW000T0101A1", "name": "台灣科技", "currency": "TWD",
             "units": 100.5, "cost_twd": 10000}]})
        self.assertEqual(errors, {})
        self.assertIsNone(clean["funds"][0]["fundclear_code"])
        self.assertTrue(clean["display"]["enabled"])

    def test_rejects_bad_isin_long_name_and_bad_numbers(self) -> None:
        _, errors = funds.validate({"funds": [
            {"isin": "ABC", "name": "一個非常非常長的基金名稱", "currency": "USD", "units": 1},
            {"isin": "LU0171310443", "name": "", "currency": "GBP", "units": 1.23456, "cost_twd": 1.5},
            {"isin": "LU0171310443", "name": "x", "currency": "EUR", "units": 0,
             "fundclear_code": "bad code!", "site": "moon"},
        ]})
        for key in ("funds[0].isin", "funds[0].name", "funds[1].name", "funds[1].currency",
                    "funds[1].units", "funds[1].cost_twd", "funds[2].units",
                    "funds[2].fundclear_code", "funds[2].site"):
            self.assertIn(key, errors)
        self.assertEqual(errors["funds[2].isin"], "這檔已經在列表裡")

    def test_count_limit(self) -> None:
        _, errors = funds.validate({"funds": []})
        self.assertIn("funds", errors)


class SummarizeTests(unittest.TestCase):
    def test_formulas_fx_and_dates(self) -> None:
        cfg = _cfg(("LU0000000001", "世界科技", "USD", 100, 200_000),
                   ("TW000T0101A1", "台灣科技", "TWD", 1000, None))
        snap = _snap(("LU0000000001", 80.0, 100.0, "2026-09-25"),
                     ("TW000T0101A1", 110.0, 100.0, "2026-09-26"), fx={"USD": 30.0})
        card = funds.summarize(cfg, snap)
        # 世界科技:市值 80×100×30 = 240,000,前值 300,000;台灣科技:110,000 / 100,000
        # 最新漲跌 = (350,000 − 400,000) / 400,000 = −12.5%
        self.assertEqual(card["day_pct"], "▼12.50%")
        self.assertEqual(card["day_pnl"], f"{MINUS}NT$ 50,000")
        self.assertEqual(card["total_value"], "350,000")
        # 總獲利只算有成本的:240,000 − 200,000
        self.assertEqual(card["profit"], {"value": "+NT$ 40,000", "sub": "▲20.00%",
                                          "note": "部分未填成本"})
        self.assertEqual(card["status"], "淨值日 09/26")
        self.assertEqual(card["earliest"], "09/25")
        # 依台幣市值排序;單檔漲跌用原幣計算
        self.assertEqual(card["top"][0], {"name": "世界科技", "pct": "▼20.00%", "ret": "累計 ▲20.00%"})
        self.assertEqual(card["top"][1], {"name": "台灣科技", "pct": "▲10.00%", "ret": "累計 --"})

    def test_top_three_and_missing_nav_or_fx(self) -> None:
        cfg = _cfg(*[(f"TW000T010{i}A1", f"基金{i}", "TWD", 10 * (i + 1), None) for i in range(4)],
                   ("LU0000000001", "缺匯率", "EUR", 1, None),
                   ("LU0000000002", "缺淨值", "USD", 1, None))
        snap = _snap(*[(f"TW000T010{i}A1", 10.0, 10.0, "2026-09-26") for i in range(4)],
                     ("LU0000000001", 10.0, 9.0, "2026-09-25"))
        card = funds.summarize(cfg, snap)
        self.assertEqual([t["name"] for t in card["top"]], ["基金3", "基金2", "基金1"])
        self.assertEqual(card["missing"], 2)
        self.assertEqual(card["earliest"], "")
        self.assertEqual(card["profit"], {"value": "--", "sub": "未填投入成本", "note": ""})
        self.assertEqual(card["day_pct"], "—0.00%")

    def test_no_funds_means_no_card(self) -> None:
        self.assertIsNone(funds.summarize(_cfg(), None))


class ParseTests(unittest.TestCase):
    def test_five_dates_latest_is_one_date_and_skips_blanks(self) -> None:
        data = {"data": {"dateList": ["2026/09/21", "2026/09/22", "2026/09/23", "2026/09/24", "2026/09/29"],
                         "offshoreQueryResultVO": [{"fundCode": "BLKTEHBJ", "oneDate": "1,405.000000",
                                                    "twoDate": "-", "threeDate": "1,398.5",
                                                    "fourDate": "", "fiveDate": "1,390"}]}}
        self.assertEqual(parse_five_dates(data, "BLKTEHBJ"), {
            "nav": 1405.0, "prev_nav": 1398.5,
            "nav_date": "2026-09-29", "prev_nav_date": "2026-09-23"})
        self.assertIsNone(parse_five_dates(data, "OTHER"))
        self.assertIsNone(parse_five_dates(None, "BLKTEHBJ"))

    def test_bot_csv_uses_spot_buying_rate(self) -> None:
        text = ("﻿幣別,匯率,現金,即期,遠期10天\n"
                "USD,本行買入,31.48000,31.80500,31.80700,本行賣出,32.15\n"
                "PHP,本行買入,0.44380,0.00000,0.00000,本行賣出,0.57580\n")
        fx = parse_bot_csv(text, 'attachment; filename="ExchangeRate@202609291902.csv"')
        self.assertEqual(fx, {"USD": 31.805, "date": "2026-09-29 19:02"})
        with self.assertRaises(RuntimeError):
            parse_bot_csv("<!DOCTYPE html><title>Challenge Validation</title>")


class ScheduleTests(unittest.TestCase):
    def test_funds_run_at_0830_and_2100(self) -> None:
        from app import scheduler
        from app.collectors.funds import FundsCollector

        fake = MagicMock()
        with patch.object(scheduler, "COLLECTORS", [FundsCollector()]), \
                patch.object(scheduler, "_sched", fake), \
                patch.object(scheduler, "settings", SimpleNamespace(refresh_via_adb=False)):
            scheduler.start()
        call = fake.add_job.call_args
        self.assertEqual(call.args[1], "cron")
        self.assertEqual((call.kwargs["hour"], call.kwargs["minute"]), ("8,21", 30))


if __name__ == "__main__":
    unittest.main()
