import unittest

from price import PriceSnapshot
from price.indicator import (
    TargetPrice,
    build_target_position,
    extract_target_price,
    format_target_detail_line,
    format_target_position_line,
    parse_target_price_value,
)


class PriceIndicatorTests(unittest.TestCase):
    def test_extract_target_price_prefers_base_target(self) -> None:
        text = (
            "\ubaa9\ud45c\uc8fc\uac00: 95,000\uc6d0\n"
            "\ud604\uc7ac \uc8fc\uac00(70,000\uc6d0)\uac00 Base \ubaa9\ud45c\uac00(61,000\uc6d0)\ub97c \uc0c1\ud68c"
        )

        target = extract_target_price(text)

        self.assertIsNotNone(target)
        self.assertEqual(target.display, "61,000\uc6d0")
        self.assertEqual(target.value, 61000)
        self.assertTrue(target.is_base)

    def test_extract_target_price_handles_krw_and_usd_forms(self) -> None:
        krw = extract_target_price("\ubaa9\ud45c\uc8fc\uac00: 95,000\uc6d0")
        usd = extract_target_price("\ubaa9\ud45c\uc8fc\uac00: $180 (12\uae30\uac04 \ubaa9\ud45c\uac00)")

        self.assertEqual(krw.value if krw else None, 95000)
        self.assertEqual(usd.value if usd else None, 180)
        self.assertEqual(usd.display if usd else None, "$180")

    def test_extract_target_price_returns_none_when_absent(self) -> None:
        self.assertIsNone(extract_target_price("\ubaa9\ud45c \uace0\uac1d\uc0ac\ub294 ESS \uc0ac\uc5c5\uc790"))

    def test_extract_target_price_rejects_non_price_numbers(self) -> None:
        text = (
            "2025\ub144 \uc2e4\uc801 \uae30\uc900 \ubaa9\ud45c\uac00 \ub17c\uc758\n"
            "2027E EPS 3,087\uc6d0, PER 20\ubc30\n"
            "VRN11 \ubaa9\ud45c\uac00 \ub17c\uc758"
        )

        self.assertIsNone(extract_target_price(text))

    def test_extract_target_price_rejects_eps_amount_even_with_target_context(self) -> None:
        text = "Base \ubaa9\ud45c\uac00 \uc0b0\uc815: 2027E EPS 3,087\uc6d0 x PER 20\ubc30"

        self.assertIsNone(extract_target_price(text))

    def test_extract_target_price_prefers_currency_amount_over_years(self) -> None:
        text = "2027\ub144 \uc774\ud6c4 Bull \ucf00\uc774\uc2a4, \ud604\uc7ac \uc8fc\uac00(70,000\uc6d0), Base \ubaa9\ud45c\uac00(61,000\uc6d0)"

        target = extract_target_price(text)

        self.assertIsNotNone(target)
        self.assertEqual(target.display if target else None, "61,000\uc6d0")

    def test_extract_target_price_builds_weighted_average_for_three_scenarios(self) -> None:
        text = (
            "Bear \ubaa9\ud45c\uac00: 37,000\uc6d0\n"
            "Base \ubaa9\ud45c\uac00: 61,000\uc6d0\n"
            "Bull \ubaa9\ud45c\uac00: 97,000\uc6d0"
        )

        target = extract_target_price(text)

        self.assertIsNotNone(target)
        self.assertEqual(target.value if target else None, 64000)
        self.assertEqual(target.display if target else None, "64,000\uc6d0")
        self.assertEqual(
            [(scenario.label, scenario.value) for scenario in (target.scenarios if target else ())],
            [("bear", 37000), ("base", 61000), ("bull", 97000)],
        )
        self.assertEqual(target.representative_label if target else None, "weighted_average")

    def test_extract_target_price_uses_base_when_scenarios_are_incomplete(self) -> None:
        text = "Bear \ubaa9\ud45c\uac00: 37,000\uc6d0\nBase \ubaa9\ud45c\uac00: 61,000\uc6d0"

        target = extract_target_price(text)

        self.assertEqual(target.value if target else None, 61000)
        self.assertEqual(target.display if target else None, "61,000\uc6d0")
        self.assertEqual(target.representative_label if target else None, "base")

    def test_indicator_gauge_thresholds(self) -> None:
        cases = [
            (60, "[\u2593\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591]"),
            (80, "[\u2593\u2593\u2593\u2593\u2593\u2593\u2591\u2591\u2591\u2591]"),
            (99, "[\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2591]"),
            (100, "[\U0001f525 OVER TARGET]"),
            (120, "[\U0001f525 OVER TARGET]"),
        ]
        target = TargetPrice(display="100", value=100)

        for current, gauge in cases:
            with self.subTest(current=current):
                position = build_target_position(PriceSnapshot(ticker="T", fetched_at="now", last_close=current), target)
                self.assertEqual(position.gauge, gauge)

    def test_indicator_handles_missing_values(self) -> None:
        missing_target = build_target_position(PriceSnapshot(ticker="T", fetched_at="now", last_close=10), None)
        missing_price = build_target_position(
            PriceSnapshot(ticker="T", fetched_at="now"),
            TargetPrice(display="100", value=100),
        )

        self.assertIn("\ubaa9\ud45c\uc8fc\uac00 \uc5c6\uc74c", format_target_position_line(missing_target))
        self.assertIn("\ud604\uc7ac\uac00 \uc5c6\uc74c", format_target_position_line(missing_price))

    def test_indicator_preserves_suspicious_target_warning(self) -> None:
        position = build_target_position(
            PriceSnapshot(ticker="T", fetched_at="now", last_close=266000),
            TargetPrice(display="11", value=11),
        )

        self.assertEqual(position.warnings, ("suspicious_target_price",))

    def test_parse_target_price_value_parses_summary_field_without_keyword(self) -> None:
        target = parse_target_price_value("95,000\uc6d0")

        self.assertEqual(target.value if target else None, 95000)

    def test_parse_target_price_value_ignores_upside_percent(self) -> None:
        self.assertIsNone(parse_target_price_value("\uc0c1\uc2b9\uc5ec\ub825 25%"))

    def test_parse_target_price_value_rejects_identifier_and_year_noise(self) -> None:
        text = "VRN11\uc740 2027E EPS \uae30\uc900\uc73c\ub85c \uc131\uc7a5\ud55c\ub2e4."

        self.assertIsNone(parse_target_price_value(text))

    def test_format_target_detail_line_shows_all_scenarios(self) -> None:
        target = parse_target_price_value(
            "Bear \ubaa9\ud45c\uac00: 37,000\uc6d0\n"
            "Base \ubaa9\ud45c\uac00: 61,000\uc6d0\n"
            "Bull \ubaa9\ud45c\uac00: 97,000\uc6d0"
        )
        position = build_target_position(PriceSnapshot(ticker="T", fetched_at="now", last_close=54300), target)

        detail = format_target_detail_line(position)

        self.assertIn("Bear: 37,000\uc6d0", detail)
        self.assertIn("Base: 61,000\uc6d0", detail)
        self.assertIn("Bull: 97,000\uc6d0", detail)
        self.assertIn("\uac00\uc911\ud3c9\uade0 \ubaa9\ud45c\uac00: 64,000\uc6d0", detail)


if __name__ == "__main__":
    unittest.main()
