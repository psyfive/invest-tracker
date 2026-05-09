import tempfile
import unittest
from pathlib import Path

from automation.pipeline import parse_report_folder_name, report_bundles_from_directory


class ReportPipelineTests(unittest.TestCase):
    def test_parse_report_folder_name_normalizes_korean_ticker_suffix(self) -> None:
        parsed = parse_report_folder_name("\ubc15\uc2e0\uc601,\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4,107640.kq,26.04")

        self.assertEqual(parsed["presenter"], "\ubc15\uc2e0\uc601")
        self.assertEqual(parsed["company"], "\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4")
        self.assertEqual(parsed["ticker"], "107640.KQ")
        self.assertEqual(parsed["presentation_month"], "26.04")

    def test_parse_report_folder_name_normalizes_ks_suffix(self) -> None:
        parsed = parse_report_folder_name("\uae40, \uc0bc\uc131\uc804\uc790, 005930.ks, 26.04")

        self.assertEqual(parsed["ticker"], "005930.KS")

    def test_parse_report_folder_name_rejects_invalid_field_count(self) -> None:
        with self.assertRaises(ValueError):
            parse_report_folder_name("\ubc15\uc2e0\uc601,\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4,107640.kq")

    def test_report_bundles_skip_invalid_folder_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            valid = root / "\ubc15\uc2e0\uc601,\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4,107640.kq,26.04"
            invalid = root / "invalid"
            valid.mkdir()
            invalid.mkdir()
            (valid / "notes.txt").write_text("body", encoding="utf-8")
            (invalid / "notes.txt").write_text("body", encoding="utf-8")

            bundles = report_bundles_from_directory(root)

        self.assertEqual(len(bundles), 1)
        self.assertEqual(bundles[0].title, "\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4")
        self.assertEqual(bundles[0].author, "\ubc15\uc2e0\uc601")
        self.assertEqual(bundles[0].ticker, "107640.KQ")
        self.assertEqual(bundles[0].presentation_month, "26.04")


if __name__ == "__main__":
    unittest.main()
