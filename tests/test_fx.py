from __future__ import annotations

import unittest

from app.collectors.fx import parse, roll
from app.render.view import _fx

CSV = (
    "﻿幣別,匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,遠期120天,遠期150天,遠期180天,"
    "匯率,現金,即期,遠期10天,遠期30天,遠期60天,遠期90天,遠期120天,遠期150天,遠期180天\n"
    "USD,本行買入,31.47500,31.82500,0,0,0,0,0,0,0,本行賣出,32.14500,31.92500,0,0,0,0,0,0,0,\n"
    "JPY,本行買入,0.19220,0.19950,0,0,0,0,0,0,0,本行賣出,0.20500,0.20350,0,0,0,0,0,0,0,\n"
)
NAME = 'attachment; filename="ExchangeRate@202610011419.csv"'


class FxParseTests(unittest.TestCase):
    def test_spot_mid_rate_and_timestamp(self) -> None:
        self.assertEqual(parse(CSV, NAME),
                         {"date": "2026-10-01", "time": "14:19", "USD": 31.875, "JPY": 0.2015})

    def test_raises_when_currency_or_time_missing(self) -> None:
        with self.assertRaises(RuntimeError):
            parse(CSV.split("JPY")[0], NAME)
        with self.assertRaises(RuntimeError):
            parse(CSV, "")


class FxRollTests(unittest.TestCase):
    def test_new_day_rolls_old_value_into_prev(self) -> None:
        old = {"date": "2026-09-30", "time": "16:00", "USD": 31.5, "JPY": 0.2, "prev": {"date": "x"}}
        new = roll({"date": "2026-10-01", "time": "09:10", "USD": 31.8, "JPY": 0.21}, old)
        self.assertEqual(new["prev"], {"date": "2026-09-30", "USD": 31.5, "JPY": 0.2})

    def test_same_day_keeps_prev(self) -> None:
        old = {"date": "2026-10-01", "USD": 31.6, "JPY": 0.2, "prev": {"date": "2026-09-30", "USD": 31.5}}
        new = roll({"date": "2026-10-01", "USD": 31.8, "JPY": 0.21}, old)
        self.assertEqual(new["prev"], {"date": "2026-09-30", "USD": 31.5})
        self.assertIsNone(roll({"date": "2026-10-01"}, None)["prev"])


class FxViewTests(unittest.TestCase):
    def test_jpy_inverted_and_change_vs_prev(self) -> None:
        p = {"date": "2026-09-30", "time": "16:00", "USD": 32.0, "JPY": 0.2,
             "prev": {"USD": 31.68, "JPY": 0.2}}
        jpy = _fx(p, "JPY", "1 台幣", "日圓", invert=True, digits=3)
        self.assertEqual((jpy["value"], jpy["change"]), ("5.000", "與前日持平"))
        self.assertEqual(jpy["stamp"], "09/30")
        usd = _fx(p, "USD", "1 美元", "台幣", invert=False, digits=2)
        self.assertEqual((usd["value"], usd["change"]), ("32.00", "較前日 +1.01%"))
        self.assertIsNone(_fx(None, "USD", "1 美元", "台幣", invert=False, digits=2))


if __name__ == "__main__":
    unittest.main()
