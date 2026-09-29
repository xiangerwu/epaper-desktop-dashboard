from __future__ import annotations

import unittest

from app.collectors.almanac import parse

LABEL = '<div class="MuiGrid-root Calendar-module__x__infoGrid1"><div class="  Calendar-module__x__{k}O  ">{l}</div></div>'
BODY = '<div class="MuiGrid-root Calendar-module__x__infoGrid2 css-1">{v}</div>'
PAGE = (
    '<a href="2026-09-28#calendar">前一天</a> 2026/09/29 (二)<a>後一天</a>'
    + LABEL.format(k="yi", l="宜") + "<style>.css-1{flex:0}</style>" + BODY.format(v="祭祀、冠笄、捕捉、餘事勿取")
    + LABEL.format(k="ji", l="忌") + BODY.format(v="嫁娶、開市、蓋屋、作梁、合壽木")
    # 頁面後段的「各時辰宜忌」,結構相同但不是整日的
    + "<div>23:00-01:00</div>" + LABEL.format(k="yi", l="宜") + BODY.format(v="祈福、求嗣")
)


class AlmanacParseTests(unittest.TestCase):
    def test_takes_first_yi_ji_after_date_header(self) -> None:
        self.assertEqual(parse(PAGE), {
            "date": "2026-09-29",
            "yi": ["祭祀", "冠笄", "捕捉", "餘事勿取"],
            "ji": ["嫁娶", "開市", "蓋屋", "作梁", "合壽木"],
        })

    def test_raises_when_structure_changes(self) -> None:
        with self.assertRaises(ValueError):
            parse("<html>改版了</html>")
        with self.assertRaises(ValueError):
            parse("2026/09/29 (二)" + LABEL.format(k="yi", l="宜"))


if __name__ == "__main__":
    unittest.main()
