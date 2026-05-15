import unittest

from summarizer.overview import NO_INFO, normalize_overview_lines, overview_items


CORE_BM = "\ud575\uc2ec BM"
MARKET_POSITION = "\ud604\uc7ac \uc2dc\uc7a5 \uc9c0\uc704"
GROWTH_MOMENTUM = "\uc55e\uc73c\ub85c\uc758 \uc131\uc7a5 \ubaa8\uba58\ud140"
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

        self.assertEqual(
            lines,
            [
                f"{CORE_BM}: ESS \ub0c9\uac01 \ubd80\ud488\uc744 \uacf5\uae09\ud55c\ub2e4. [\ucd9c\ucc98: deck.pdf]",
                f"{MARKET_POSITION}: {NO_INFO}",
                f"{GROWTH_MOMENTUM}: {NO_INFO}",
            ],
        )

    def test_missing_source_uses_source_unavailable_marker(self) -> None:
        lines = normalize_overview_lines("", "")

        self.assertEqual(
            lines,
            [
                f"{CORE_BM}: {NO_INFO}",
                f"{MARKET_POSITION}: {NO_INFO}",
                f"{GROWTH_MOMENTUM}: {NO_INFO}",
            ],
        )

    def test_legacy_labels_are_mapped_to_new_labels(self) -> None:
        lines = normalize_overview_lines(
            "\n".join(
                [
                    f"{CORE_BM}: ESS \ub0c9\uac01 {SOURCE}",
                    f"\uc2dc\uc7a5 \uc9c0\uc704: \uc8fc\uc694 \ubca4\ub354 {SOURCE}",
                    f"\uc131\uc7a5 \ubaa8\uba58\ud140: \uc591\uc0b0 \ud655\ub300 {SOURCE}",
                ]
            )
        )

        self.assertTrue(lines[1].startswith(f"{MARKET_POSITION}:"))
        self.assertTrue(lines[2].startswith(f"{GROWTH_MOMENTUM}:"))

    def test_overview_items_split_labels_from_content_for_rendering(self) -> None:
        items = overview_items(
            "\n".join(
                [
                    f"{CORE_BM}: ESS \ub0c9\uac01 {SOURCE}",
                    f"{MARKET_POSITION}: {NO_INFO}",
                    f"{GROWTH_MOMENTUM}: \uc591\uc0b0 \ud655\ub300 {SOURCE}",
                ]
            )
        )

        self.assertEqual(
            items,
            [
                (CORE_BM, f"ESS \ub0c9\uac01 {SOURCE}"),
                (MARKET_POSITION, NO_INFO),
                (GROWTH_MOMENTUM, f"\uc591\uc0b0 \ud655\ub300 {SOURCE}"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
