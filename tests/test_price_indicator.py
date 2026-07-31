import unittest

from price import PriceSnapshot
from price.indicator import (
    TargetPrice,
    build_target_position,
    extract_target_price,
    format_target_detail_line,
    format_target_position_line,
    format_target_price_source_text,
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

    def test_extract_target_price_reads_amount_on_following_line(self) -> None:
        """발표자료는 목표주가를 도형 제목으로 두고 금액을 다음 줄에 두는 경우가 많다."""
        text = "\n".join(
            [
                "--- Slide 24 ---",
                "목표주가 벨류에이션 산정",
                "벨류에이션 계산 - PSR 멀티플산정",
                "2026 년 : 매출 270 억* PSR 36 / 21,346,230 주 = 45,000 원",
            ]
        )

        target = extract_target_price(text)

        self.assertIsNotNone(target)
        self.assertEqual(target.value if target else None, 45000)

    def test_extract_target_price_reads_broker_consensus_table(self) -> None:
        text = "\n".join(
            [
                "증권사별 목표 주가 (2026년도)",
                "LS 증권 531,000원 (06.Jun.2026)",
                "IM 증권 800,000원 (11.May.2026)",
                "한화투자증권 430,000원 (3.Feb.2026)",
            ]
        )

        target = extract_target_price(text)

        self.assertIsNotNone(target)
        self.assertEqual(target.value if target else None, 531000)
        self.assertTrue(target.is_consensus if target else False)

    def test_extract_target_price_builds_scenarios_from_label_rows(self) -> None:
        """라벨과 금액이 별도 줄인 시나리오 표에서도 가중평균이 나와야 한다."""
        text = "\n".join(
            [
                "안전마진  ·  목표주가  ·  투자 전략",
                "안전마진  (Bear · 희석 기준)",
                "₩ 37,000원  (−53%)",
                "Base 목표주가  (2026.12)",
                "₩ 61,000원  (-13%)",
                "Bull 목표주가  (AI 인프라 프리미엄)",
                "₩ 97,000원  (+38%)",
            ]
        )

        target = extract_target_price(text)

        self.assertIsNotNone(target)
        self.assertEqual(target.representative_label if target else None, "weighted_average")
        self.assertEqual(target.value if target else None, 64000)
        self.assertEqual(
            [(scenario.label, scenario.value) for scenario in (target.scenarios if target else ())],
            [("bear", 37000), ("base", 61000), ("bull", 97000)],
        )

    def test_extract_target_price_ignores_non_target_amounts_under_heading(self) -> None:
        """목표가 헤딩 아래라도 매집 구간·현재가 같은 금액은 목표가가 아니다."""
        text = "\n".join(
            [
                "Base 목표주가",
                "₩ 61,000원",
                "이상적 매집 구간: ₩45,000 이하",
                "차익 실현 검토 구간: ₩75,000 이상",
            ]
        )

        target = extract_target_price(text)

        self.assertEqual(target.value if target else None, 61000)

    def test_extract_target_price_ignores_unitless_amount_on_following_line(self) -> None:
        text = "목표주가 산정 근거\n산업 평균 멀티플 36 적용"

        self.assertIsNone(extract_target_price(text))

    def test_extract_target_price_keeps_distant_amount_out_of_scope(self) -> None:
        lines = ["목표주가 산정 근거"] + ["설명 줄"] * 12 + ["12,345원"]

        self.assertIsNone(extract_target_price("\n".join(lines)))

    def test_format_target_price_source_text_marks_consensus(self) -> None:
        target = extract_target_price(
            "증권사별 목표 주가\nLS 증권 531,000원"
        )

        text = format_target_price_source_text(target)

        self.assertIn("증권사 컨센서스", text)
        self.assertIn("531,000원", text)
        # 렌더러가 이 문자열을 다시 파싱해도 컨센서스 표시가 유지돼야 한다.
        reparsed = parse_target_price_value(text)
        self.assertEqual(reparsed.value if reparsed else None, 531000)
        self.assertTrue(reparsed.is_consensus if reparsed else False)

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
