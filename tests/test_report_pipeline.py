import tempfile
import unittest
from pathlib import Path

from automation.pipeline import parse_report_folder_name, report_bundles_from_directory
from main import _target_price_text_from_source


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

    def test_target_price_fallback_uses_valid_llm_value(self) -> None:
        text = "Base \ubaa9\ud45c\uac00: 61,000\uc6d0"
        fallback = "Base \ubaa9\ud45c\uac00: 95,000\uc6d0"

        self.assertEqual(_target_price_text_from_source(text, fallback), fallback)

    def test_target_price_fallback_retries_source_when_llm_value_is_not_parseable(self) -> None:
        text = (
            "Bear \ubaa9\ud45c\uac00: 37,000\uc6d0\n"
            "Base \ubaa9\ud45c\uac00: 61,000\uc6d0\n"
            "Bull \ubaa9\ud45c\uac00: 97,000\uc6d0"
        )

        target_text = _target_price_text_from_source(text, "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c")

        self.assertIn("Bear \ubaa9\ud45c\uac00: 37,000\uc6d0", target_text)
        self.assertIn("Base \ubaa9\ud45c\uac00: 61,000\uc6d0", target_text)
        self.assertIn("Bull \ubaa9\ud45c\uac00: 97,000\uc6d0", target_text)

    def test_target_price_fallback_returns_empty_when_neither_source_nor_llm_has_price(self) -> None:
        self.assertEqual(
            _target_price_text_from_source("\uc0ac\uc5c5 \uc124\uba85\ub9cc \uc788\uc74c", "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
