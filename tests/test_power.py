from __future__ import annotations

import unittest

from app.collectors.power import parse

DATA = {"DateTime": "2026-09-29T15:30:00", "aaData": [
    {"機組類型": "燃氣", "機組名稱": "大潭CC#1", "裝置容量(MW)": "742.7", "淨發電量(MW)": "696.0"},
    {"機組類型": "燃氣", "機組名稱": "小計", "裝置容量(MW)": "15918.1(26.049%)", "淨發電量(MW)": "16839.5(43.040%)"},
    {"機組類型": "民營電廠-燃氣", "機組名稱": "小計", "裝置容量(MW)": "6389.7(10.456%)", "淨發電量(MW)": "5021.5(12.834%)"},
    {"機組類型": "風力", "機組名稱": "小計(註5)", "裝置容量(MW)": "4187.1(6.852%)", "淨發電量(MW)": "717.6(1.834%)"},
    {"機組類型": "儲能負載(Energy Storage System Load)</b>", "機組名稱": "某站", "裝置容量(MW)": "1", "淨發電量(MW)": "-1"},
]}


class PowerParseTests(unittest.TestCase):
    def test_only_subtotals_with_share_and_short_names(self) -> None:
        self.assertEqual(parse(DATA), {"date": "2026-09-29", "time": "15:30", "types": [
            {"name": "燃氣", "mw": 16839.5, "share": 43.04},
            {"name": "民營燃氣", "mw": 5021.5, "share": 12.834},
            {"name": "風力", "mw": 717.6, "share": 1.834},
        ]})

    def test_raises_without_subtotals(self) -> None:
        with self.assertRaises(ValueError):
            parse({"DateTime": "2026-09-29T15:30:00", "aaData": []})


if __name__ == "__main__":
    unittest.main()
