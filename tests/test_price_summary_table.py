import unittest

from price import PriceSnapshot
<<<<<<< HEAD
from price.summary_table import CURRENT_LABEL, PRESENTATION_LABEL, PREV_LABEL, build_price_summary_rows
=======
from price.summary_table import MONTHLY_CLOSE_LABEL_PREFIX, PRESENTATION_LABEL, build_price_summary_rows
>>>>>>> db41634 (Add monthly close rows to price summary)


class PriceSummaryTableTests(unittest.TestCase):
    def _make_snap(self, monthly_closes=None):
        return PriceSnapshot(
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
            monthly_closes=monthly_closes or [],
        )

    def test_row_order_is_chronological(self):
        snap = self._make_snap(monthly_closes=[
            {"date": "2026-05-30", "close": 950, "market_cap": 1e12, "label": "2026.05 종가"},
        ])
        rows = build_price_summary_rows(snap)
        labels = [r.label for r in rows]
        self.assertEqual(labels, [PRESENTATION_LABEL, "2026.05 종가", PREV_LABEL, CURRENT_LABEL])

    def test_no_monthly_closes_gives_four_rows(self):
        snap = self._make_snap()
        rows = build_price_summary_rows(snap)
        labels = [r.label for r in rows]
        self.assertEqual(labels, [PRESENTATION_LABEL, PREV_LABEL, CURRENT_LABEL])

    def test_presentation_change_pct_is_none(self):
        snap = self._make_snap()
        presentation_row = next(r for r in build_price_summary_rows(snap) if r.label == PRESENTATION_LABEL)
        self.assertIsNone(presentation_row.change_pct)

    def test_current_change_pct_vs_presentation(self):
        snap = self._make_snap()
        current_row = next(r for r in build_price_summary_rows(snap) if r.label == CURRENT_LABEL)
        self.assertEqual(current_row.change_pct, 63.93)

    def test_prev_row_has_no_market_cap(self):
        snap = self._make_snap()
        prev_row = next(r for r in build_price_summary_rows(snap) if r.label == PREV_LABEL)
        self.assertIsNone(prev_row.market_cap)

    def test_monthly_row_market_cap_populated(self):
        snap = self._make_snap(monthly_closes=[
            {"date": "2026-05-30", "close": 950, "market_cap": 1.5e12, "label": "2026.05 종가"},
        ])
        monthly_row = next(r for r in build_price_summary_rows(snap) if r.label == "2026.05 종가")
        self.assertEqual(monthly_row.market_cap, 1.5e12)

    def test_monthly_close_rows_are_appended_after_presentation_row(self) -> None:
        snap = PriceSnapshot(
            ticker="000001.KS",
            fetched_at="now",
            last_close=1200,
            prev_close=1180,
            presentation_close={"date": "2026-04-30", "close": 1000},
            last_5_closes=[
                {"date": "2026-06-24", "close": 1160},
                {"date": "2026-06-25", "close": 1170},
                {"date": "2026-06-26", "close": 1180},
                {"date": "2026-06-29", "close": 1190},
                {"date": "2026-06-30", "close": 1200},
            ],
            monthly_closes=[
                {"date": "2026-04-30", "close": 1000},
                {"date": "2026-05-29", "close": 1100},
                {"date": "2026-06-30", "close": 1200},
            ],
        )

        rows = build_price_summary_rows(snap)
        monthly_rows = [
            row for row in rows
            if row.label.startswith(MONTHLY_CLOSE_LABEL_PREFIX)
        ]

        self.assertEqual([row.label for row in monthly_rows], ["월별 종가 2026-05"])
        self.assertEqual(monthly_rows[0].date, "2026-05-29")
        self.assertEqual(monthly_rows[0].change_pct, 10.0)


if __name__ == "__main__":
    unittest.main()
