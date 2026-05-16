import unittest

from price import PriceSnapshot
from price.summary_table import PRESENTATION_LABEL, build_price_summary_rows


class PriceSummaryTableTests(unittest.TestCase):
    def test_presentation_row_uses_change_vs_current_price(self) -> None:
        snap = PriceSnapshot(
            ticker="000001.KS",
            fetched_at="now",
            last_close=1000,
            prev_close=990,
            change_pct=1.01,
            presentation_close={"date": "2026-04-30", "close": 610, "change_pct": -0.81},
            last_5_closes=[
                {"date": "2026-05-07", "close": 970},
                {"date": "2026-05-08", "close": 980},
                {"date": "2026-05-11", "close": 985},
                {"date": "2026-05-12", "close": 990},
                {"date": "2026-05-13", "close": 1000},
            ],
        )

        presentation_row = next(
            row for row in build_price_summary_rows(snap)
            if row.label == PRESENTATION_LABEL
        )

        self.assertEqual(presentation_row.change_pct, 63.93)


if __name__ == "__main__":
    unittest.main()
