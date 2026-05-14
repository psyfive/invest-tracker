import unittest

from summarizer.overview import NO_INFO, normalize_overview_lines


CORE_BM = "\ud575\uc2ec BM"
MARKET_POSITION = "\uc2dc\uc7a5 \uc9c0\uc704"
GROWTH_MOMENTUM = "\uc131\uc7a5 \ubaa8\uba58\ud140"
SOURCE = "[\ucd9c\ucc98: deck.pdf]"


class OverviewNormalizationTests(unittest.TestCase):
    def test_keeps_labeled_three_line_overview(self) -> None:
        lines = normalize_overview_lines(
            "\n".join(
                [
                    f"{CORE_BM}: ESS \ub0c9\uac01 \ubd80\ud488 \uacf5\uae09\uc0ac {SOURCE}",
                    f"{MARKET_POSITION}: \uc8fc\uc694 \uace0\uac1d\uc0ac \ubca4\ub354 {SOURCE}",
                    f"{GROWTH_MOMENTUM}: 2026\ub144 \uc591\uc0b0 \uc608\uc815 {SOURCE}",
                ]
            ),
            "fallback.txt",
        )

        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith(f"{CORE_BM}:"))
        self.assertTrue(lines[1].startswith(f"{MARKET_POSITION}:"))
        self.assertTrue(lines[2].startswith(f"{GROWTH_MOMENTUM}:"))
        self.assertTrue(all(SOURCE in line for line in lines))

    def test_single_paragraph_is_normalized_and_missing_lines_are_filled(self) -> None:
        lines = normalize_overview_lines("ESS \ub0c9\uac01 \ubd80\ud488\uc744 \uacf5\uae09\ud55c\ub2e4.", "deck.pdf")

        self.assertEqual(lines, ["ESS \ub0c9\uac01 \ubd80\ud488\uc744 \uacf5\uae09\ud55c\ub2e4. [\ucd9c\ucc98: deck.pdf]"])

    def test_missing_source_uses_source_unavailable_marker(self) -> None:
        lines = normalize_overview_lines("", "")

        self.assertEqual(lines, [NO_INFO])


if __name__ == "__main__":
    unittest.main()
