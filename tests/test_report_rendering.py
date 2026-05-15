import unittest

from automation.notion import blocks_for_post
from price import PriceSnapshot
from renderer import render_post
from summarizer.base import Summary
from summarizer.llm_based import SUMMARY_PROMPT


IDEA_LABEL = "\ud22c\uc790 \uc544\uc774\ub514\uc5b4(Upside)"
RISK_LABEL = "\ud22c\uc790 \ub9ac\uc2a4\ud06c(Downside)"
TREND_LABEL = "\uc2e4\uc2dc\uac04 \uc8fc\uac00 \ucd94\uc774"
SOURCE_MARKER = "[\ucd9c\ucc98: deck.pdf]"
PRICE_INFO = "\uc8fc\uac00 \uc815\ubcf4"
CONCLUSION = "\uacb0\ub860"
REMOVED_CONCLUSION = "\uc0ad\uc81c\ub418\uc5b4\uc57c \ud558\ub294 \uacb0\ub860"
TARGET_POSITION = "\ubaa9\ud45c\uac00 \ub300\ube44 \uc704\uce58"
PRICE_SUMMARY = "\uc8fc\uac00 \uc694\uc57d \ud45c"
CURRENT_PRICE = "\ud604\uc7ac\uac00"
PREV_CLOSE = "\uc804\uc77c \uc885\uac00"
TWO_DAYS_AGO_CLOSE = "\uc774\ud2c0 \uc804 \uc885\uac00"
PRESENTATION_CLOSE = "\ubc1c\ud45c\uc2dc\uc810 \uc885\uac00"
CHANGE_PCT = "\ub4f1\ub77d\ub960"
MARKET_CAP = "\uc2dc\uac00\ucd1d\uc561"
CORE_BM = "\ud575\uc2ec BM"
MARKET_POSITION = "\ud604\uc7ac \uc2dc\uc7a5 \uc9c0\uc704"
GROWTH_MOMENTUM = "\uc55e\uc73c\ub85c\uc758 \uc131\uc7a5 \ubaa8\uba58\ud140"
NO_INFO = "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c"


class ReportRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = Summary(
            company="A Corp",
            ticker="000001.KS",
            presenter="Kim",
            presentation_month="26.04",
            overview=(
                f"{CORE_BM}: ESS \ub0c9\uac01 \ubd80\ud488\uc744 \uacf5\uae09\ud55c\ub2e4. {SOURCE_MARKER}\n"
                f"{MARKET_POSITION}: {NO_INFO}\n"
                f"{GROWTH_MOMENTUM}: 2026\ub144 \uc591\uc0b0 \uc608\uc815 {SOURCE_MARKER}"
            ),
            thesis=(
                f"- \uc218\ub0c9\uc2dd \ub0c9\uac01 \uc2dc\uc2a4\ud15c \ub9e4\ucd9c \ube44\uc911 40% {SOURCE_MARKER}\n"
                f"- \uc2e0\uaddc \uace0\uac1d\uc0ac \ud655\ub300 {SOURCE_MARKER}"
            ),
            risks=(
                f"- \uace0\uac1d\uc0ac \ubc1c\uc8fc \uc9c0\uc5f0 \uc2dc \ub9e4\ucd9c \uc778\uc2dd \uc9c0\uc5f0 {SOURCE_MARKER}\n"
                f"- \uc6d0\uc7ac\ub8cc \uac00\uaca9 \uc0c1\uc2b9 {SOURCE_MARKER}"
            ),
            conclusion=REMOVED_CONCLUSION,
            target_price="2,000\uc6d0",
        )
        self.snap = PriceSnapshot(
            ticker="000001.KS",
            fetched_at="now",
            last_close=1000,
            prev_close=990,
            change_pct=1.01,
            currency="KRW",
            market_cap=4_200_000_000_000,
            presentation_close={"date": "2026-04-30", "close": 610, "change_pct": -0.81},
            last_5_closes=[
                {"date": "2026-05-07", "close": 970},
                {"date": "2026-05-08", "close": 980},
                {"date": "2026-05-11", "close": 985},
                {"date": "2026-05-12", "close": 990},
                {"date": "2026-05-13", "close": 1000},
            ],
        )

    def test_html_renders_investment_table_and_price_trend_toggle(self) -> None:
        html = render_post(self.summary, self.snap, sources=["deck.pdf"])

        self.assertIn(IDEA_LABEL, html)
        self.assertIn(RISK_LABEL, html)
        self.assertIn(f"<details><summary>{TREND_LABEL}</summary>", html)
        self.assertIn(TARGET_POSITION, html)
        self.assertIn("50.0%", html)
        self.assertIn(PRICE_SUMMARY, html)
        self.assertIn(CURRENT_PRICE, html)
        self.assertIn(PREV_CLOSE, html)
        self.assertIn(TWO_DAYS_AGO_CLOSE, html)
        self.assertIn(PRESENTATION_CLOSE, html)
        self.assertIn(CHANGE_PCT, html)
        self.assertIn(MARKET_CAP, html)
        self.assertIn("1,000\uc6d0", html)
        self.assertIn("610\uc6d0", html)
        self.assertIn("4.20\uc870\uc6d0", html)
        self.assertIn(CORE_BM, html)
        self.assertIn(MARKET_POSITION, html)
        self.assertIn(GROWTH_MOMENTUM, html)
        self.assertIn(NO_INFO, html)
        self.assertIn(SOURCE_MARKER, html)
        self.assertIn('color:#d32f2f', html)
        self.assertIn('color:#1976d2', html)
        self.assertIn('<h2>Company overview</h2><ul>', html)
        self.assertGreaterEqual(html.count('style="margin-bottom:8px"'), 7)
        self.assertNotIn("Conclusion / checkpoints", html)
        self.assertNotIn(REMOVED_CONCLUSION, html)
        self.assertNotIn("Price snapshot", html)
        self.assertNotIn(PRICE_INFO, html)

    def test_notion_blocks_render_table_toggle_and_omit_removed_sections(self) -> None:
        blocks = blocks_for_post(self.summary, self.snap, sources=["deck.pdf"])
        block_types = [block["type"] for block in blocks]
        serialized = str(blocks)

        self.assertIn("toggle", block_types)
        self.assertIn("table", block_types)
        self.assertIn(TREND_LABEL, serialized)
        self.assertIn(TARGET_POSITION, serialized)
        self.assertIn("50.0%", serialized)
        self.assertIn(PRICE_SUMMARY, serialized)
        self.assertIn(CURRENT_PRICE, serialized)
        self.assertIn(PREV_CLOSE, serialized)
        self.assertIn(TWO_DAYS_AGO_CLOSE, serialized)
        self.assertIn(PRESENTATION_CLOSE, serialized)
        self.assertIn(CHANGE_PCT, serialized)
        self.assertIn(MARKET_CAP, serialized)
        self.assertIn("1,000\uc6d0", serialized)
        self.assertIn("610\uc6d0", serialized)
        self.assertIn("4.20\uc870\uc6d0", serialized)
        self.assertIn(CORE_BM, serialized)
        self.assertIn(MARKET_POSITION, serialized)
        self.assertIn(GROWTH_MOMENTUM, serialized)
        self.assertIn(NO_INFO, serialized)
        self.assertIn(IDEA_LABEL, serialized)
        self.assertIn(RISK_LABEL, serialized)
        self.assertIn(SOURCE_MARKER, serialized)
        self.assertNotIn(PRICE_INFO, serialized)
        self.assertNotIn(CONCLUSION, serialized)
        self.assertNotIn(REMOVED_CONCLUSION, serialized)

        toggle = next(block for block in blocks if block["type"] == "toggle")
        toggle_child_types = [child["type"] for child in toggle["toggle"]["children"]]
        self.assertIn("table", toggle_child_types)
        self.assertNotIn("bulleted_list_item", toggle_child_types)

        table = next(child for child in toggle["toggle"]["children"] if child["type"] == "table")
        rows = table["table"]["children"]
        current_change_cell = rows[1]["table_row"]["cells"][3][0]
        presentation_change_cell = rows[4]["table_row"]["cells"][3][0]
        self.assertEqual(current_change_cell["annotations"]["color"], "red")
        self.assertEqual(presentation_change_cell["annotations"]["color"], "blue")

        overview_heading_index = next(
            index for index, block in enumerate(blocks)
            if block["type"] == "heading_2" and CORE_BM not in str(block) and "\uae30\uc5c5 \uac1c\uc694" in str(block)
        )
        overview_blocks = blocks[overview_heading_index + 1:overview_heading_index + 4]
        self.assertTrue(all(block["type"] == "bulleted_list_item" for block in overview_blocks))

        investment_table = next(
            block for block in blocks
            if block["type"] == "table" and IDEA_LABEL in str(block)
        )
        investment_cells = investment_table["table"]["children"][1]["table_row"]["cells"]
        self.assertIn("\n\n- ", investment_cells[0][0]["text"]["content"])
        self.assertIn("\n\n- ", investment_cells[1][0]["text"]["content"])

    def test_html_does_not_invent_source_markers(self) -> None:
        summary = Summary(
            company="A Corp",
            ticker="000001.KS",
            overview="ESS \ub0c9\uac01 \ubd80\ud488\uc744 \uacf5\uae09\ud55c\ub2e4.",
            thesis="- \uc218\ub0c9\uc2dd \ub0c9\uac01 \uc2dc\uc2a4\ud15c",
            risks="- \uace0\uac1d\uc0ac \ubc1c\uc8fc \uc9c0\uc5f0",
        )

        html = render_post(summary, self.snap, sources=["voice.docx"])

        self.assertNotIn("[\ucd9c\ucc98: voice.docx]", html)

    def test_notion_price_table_uses_gray_for_flat_change(self) -> None:
        flat_snap = PriceSnapshot(
            ticker="000001.KS",
            fetched_at="now",
            last_close=1000,
            prev_close=1000,
            change_pct=0.0,
            currency="KRW",
            presentation_close={"date": "2026-04-30", "close": 610, "change_pct": 0.0},
            last_5_closes=[
                {"date": "2026-05-07", "close": 980},
                {"date": "2026-05-08", "close": 990},
                {"date": "2026-05-11", "close": 1000},
                {"date": "2026-05-12", "close": 1000},
                {"date": "2026-05-13", "close": 1000},
            ],
        )

        blocks = blocks_for_post(self.summary, flat_snap, sources=["deck.pdf"])
        html = render_post(self.summary, flat_snap, sources=["deck.pdf"])
        toggle = next(block for block in blocks if block["type"] == "toggle")
        table = next(child for child in toggle["toggle"]["children"] if child["type"] == "table")
        rows = table["table"]["children"]

        self.assertEqual(rows[1]["table_row"]["cells"][3][0]["annotations"]["color"], "gray")
        self.assertEqual(rows[4]["table_row"]["cells"][3][0]["annotations"]["color"], "gray")
        self.assertIn('color:#666', html)

    def test_price_toggle_shows_scenario_targets_and_weighted_average(self) -> None:
        summary = Summary(
            company="Scenario Corp",
            ticker="000001.KS",
            target_price=(
                "Bear \ubaa9\ud45c\uac00: 37,000\uc6d0\n"
                "Base \ubaa9\ud45c\uac00: 61,000\uc6d0\n"
                "Bull \ubaa9\ud45c\uac00: 97,000\uc6d0"
            ),
        )

        html = render_post(summary, self.snap, sources=[])
        blocks = blocks_for_post(summary, self.snap, sources=[])
        serialized = str(blocks)

        for text in (
            "Bear: 37,000\uc6d0",
            "Base: 61,000\uc6d0",
            "Bull: 97,000\uc6d0",
            "\uac00\uc911\ud3c9\uade0 \ubaa9\ud45c\uac00: 64,000\uc6d0",
        ):
            self.assertIn(text, html)
            self.assertIn(text, serialized)

    def test_llm_prompt_requires_citations_and_variable_item_counts(self) -> None:
        prompt = SUMMARY_PROMPT.format(
            company="A Corp",
            ticker="000001.KS",
            presenter="Kim",
            presentation_month="26.04",
            allowed_labels="- deck.pdf/Page 1",
            item_limits="- overview: at most 3 items",
        )

        self.assertIn(CORE_BM, prompt)
        self.assertIn(MARKET_POSITION, prompt)
        self.assertIn(GROWTH_MOMENTUM, prompt)
        self.assertIn("are not fixed to 3 items", prompt)
        self.assertIn("Every factual item must include a source", prompt)
        self.assertIn("Return JSON", prompt)
        self.assertIn("Do not output markdown fences", prompt)


if __name__ == "__main__":
    unittest.main()
