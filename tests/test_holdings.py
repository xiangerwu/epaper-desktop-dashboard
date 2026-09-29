from __future__ import annotations

import unittest
from datetime import datetime

from app import holdings
from app.collectors.stocks import parse

TPE = holdings.TPE
MINUS = "−"


def _cfg(*rows) -> dict:
    return {"holdings": [{"code": c, "shares": s, "avg_cost": a} for c, s, a in rows],
            "display": dict(holdings.DEFAULT_DISPLAY)}


def _snap(*items, date="20260929") -> dict:
    return {"quote_date": date, "items": [
        {"code": c, "name": n, "price": p, "prev_close": y} for c, n, p, y in items]}


class ValidateTests(unittest.TestCase):
    def test_accepts_minimal_payload_with_default_display(self) -> None:
        clean, errors = holdings.validate({"holdings": [{"code": "0050", "shares": 1000}]})
        self.assertEqual(errors, {})
        self.assertEqual(clean["holdings"], [{"code": "0050", "shares": 1000, "avg_cost": None}])
        self.assertEqual(clean["display"]["rotate_seconds"], 60)

    def test_rejects_bad_fields(self) -> None:
        _, errors = holdings.validate({"holdings": [
            {"code": "abc", "shares": -1},
            {"code": "00990A", "shares": 1.5, "avg_cost": 1.23456},
            {"code": "00990A", "shares": 10_000_001, "avg_cost": 0},
        ], "display": {"rotate_seconds": 5}})
        self.assertIn("holdings[0].code", errors)
        self.assertIn("holdings[0].shares", errors)
        self.assertIn("holdings[1].shares", errors)
        self.assertIn("holdings[1].avg_cost", errors)
        self.assertEqual(errors["holdings[2].code"], "這檔已經在列表裡")
        self.assertIn("holdings[2].shares", errors)
        self.assertIn("holdings[2].avg_cost", errors)
        self.assertIn("display.rotate_seconds", errors)

    def test_count_limits_and_bool_is_not_int(self) -> None:
        _, errors = holdings.validate({"holdings": []})
        self.assertIn("holdings", errors)
        _, errors = holdings.validate({"holdings": [{"code": "0050", "shares": True}]})
        self.assertIn("holdings[0].shares", errors)
        _, errors = holdings.validate({"holdings": [{"code": "0050", "shares": 1, "avg_cost": 85.2}]})
        self.assertEqual(errors, {})


class MarketHoursTests(unittest.TestCase):
    def test_update_window_includes_14_and_skips_weekend(self) -> None:
        self.assertTrue(holdings.in_update_window(datetime(2026, 9, 29, 14, 0, tzinfo=TPE)))
        self.assertFalse(holdings.in_update_window(datetime(2026, 9, 29, 8, 59, tzinfo=TPE)))
        self.assertFalse(holdings.in_update_window(datetime(2026, 10, 3, 10, 0, tzinfo=TPE)))
        self.assertFalse(holdings.in_trading_session(datetime(2026, 9, 29, 13, 30, tzinfo=TPE)))


class SummarizeTests(unittest.TestCase):
    NOW = datetime(2026, 9, 29, 11, 0, tzinfo=TPE)

    def test_totals_names_and_signs(self) -> None:
        cfg = _cfg(("0050", 1000, 100.0), ("00990A", 2000, None), ("9999", 10, None))
        snap = _snap(("0050", "元大台灣50", 110.0, 100.0),
                     ("00990A", "主動元大AI新經濟", 15.0, 16.0))
        card = holdings.summarize(cfg, snap, now=self.NOW, age_seconds=120)
        # V = 110000 + 30000, PV = 100000 + 32000 → day = +8000, +6.06%
        self.assertEqual(card["day_pct"], "▲6.06%")
        self.assertEqual(card["day_pnl"], "+NT$ 8,000")
        self.assertEqual(card["total_value"], "140,000")
        # 未實現只算 0050:(110-100)×1000
        self.assertEqual(card["unrealized"], {"value": "+NT$ 10,000", "sub": "+10.00%", "note": "部分未填成本"})
        self.assertEqual(card["weakest"], {"name": "主動元大AI新…", "pct": "▼6.25%"})
        self.assertEqual(card["strongest"]["name"], "元大台灣50")
        self.assertEqual((card["count"], card["missing"], card["down"], card["up"]), (3, 1, 1, 1))
        self.assertEqual(card["status"], "盤中・2 分前")

    def test_no_cost_and_loss_uses_unicode_minus(self) -> None:
        cfg = _cfg(("2412", 1000, None))
        card = holdings.summarize(cfg, _snap(("2412", "中華電", 140.0, 145.0), date="20260926"),
                                  now=self.NOW)
        self.assertEqual(card["day_pnl"], f"{MINUS}NT$ 5,000")
        self.assertEqual(card["unrealized"], {"value": "--", "sub": "未填平均成本", "note": ""})
        self.assertEqual(card["status"], "收盤・09/26")

    def test_no_holdings_means_no_card(self) -> None:
        self.assertIsNone(holdings.summarize(_cfg(), None))


class ParseMisTests(unittest.TestCase):
    def test_price_fallbacks_and_empty_shells(self) -> None:
        out = parse([
            {"c": "", "z": "-"},  # 另一市場前綴的空殼
            {"c": "0050", "n": "元大台灣50", "z": "-", "pz": "111.35", "y": "112.4", "d": "20260929"},
            {"c": "6488", "n": "環球晶", "z": "-", "pz": "-", "b": "941_940_", "a": "943_945_", "y": "948"},
            {"c": "2412", "n": "中華電", "z": "145.5", "y": "145"},
            {"c": "9999", "n": "?", "z": "-", "y": "-"},
        ])
        self.assertEqual(set(out), {"0050", "6488", "2412"})
        self.assertEqual(out["0050"]["price"], 111.35)
        self.assertEqual(out["6488"]["price"], 942.0)
        self.assertEqual(out["2412"]["price"], 145.5)


class InternalOnlyTests(unittest.TestCase):
    def test_lan_tailscale_and_loopback_only(self) -> None:
        from app.main import _is_internal
        for ok in ("127.0.0.1", "192.168.1.187", "10.0.0.5", "100.101.102.103",
                   "fd7a:115c:a1e0::1", "::ffff:192.168.1.2"):
            self.assertTrue(_is_internal(ok), ok)
        for bad in ("8.8.8.8", "100.128.0.1", "2001:4860::1", None, "testclient"):
            self.assertFalse(_is_internal(bad), bad)


if __name__ == "__main__":
    unittest.main()
