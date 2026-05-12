import unittest

from automation.notion import blocks_for_post
from price import PriceSnapshot
from renderer import render_post
from summarizer.base import Summary
from summarizer.llm_based import PROMPT_TEMPLATE


IDEA_LABEL = "\ud22c\uc790 \uc544\uc774\ub514\uc5b4(Upside)"
RISK_LABEL = "\ud22c\uc790 \ub9ac\uc2a4\ud06c(Downside)"
TREND_LABEL = "\uc2e4\uc2dc\uac04 \uc8fc\uac00 \ucd94\uc774"
SOURCE_MARKER = "[\ucd9c\ucc98: deck.pdf]"
PRICE_INFO = "\uc8fc\uac00 \uc815\ubcf4"
CONCLUSION = "\uacb0\ub860"
REMOVED_CONCLUSION = "\uc0ad\uc81c\ub418\uc5b4\uc57c \ud558\ub294 \uacb0\ub860"
TARGET_POSITION = "\ubaa9\ud45c\uac00 \ub300\ube44 \uc704\uce58"


class ReportRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = Summary(
            company="A Corp",
            ticker="000001.KS",
            presenter="Kim",
            presentation_month="26.04",
            overview="ESS \ub0c9\uac01 \ubd80\ud488\uc744 \uacf5\uae09\ud55c\ub2e4.",
            thesis="- \uc218\ub0c9\uc2dd \ub0c9\uac01 \uc2dc\uc2a4\ud15c \ub9e4\ucd9c \ube44\uc911 40%",
            risks="- \uace0\uac1d\uc0ac \ubc1c\uc8fc \uc9c0\uc5f0 \uc2dc \ub9e4\ucd9c \uc778\uc2dd \uc9c0\uc5f0",
            conclusion=REMOVED_CONCLUSION,
            target_price="2,000\uc6d0",
        )
        self.snap = PriceSnapshot(
            ticker="000001.KS",
            fetched_at="now",
            last_close=1000,
            last_5_closes=[
                {"date": "2026-05-08", "close": 1000},
                {"date": "2026-05-11", "close": 1010},
            ],
        )

    def test_html_renders_investment_table_and_price_trend_toggle(self) -> None:
        html = render_post(self.summary, self.snap, sources=["deck.pdf"])

        self.assertIn(IDEA_LABEL, html)
        self.assertIn(RISK_LABEL, html)
        self.assertIn(f"<details><summary>{TREND_LABEL}</summary>", html)
        self.assertIn(TARGET_POSITION, html)
        self.assertIn("50.0%", html)
        self.assertIn(SOURCE_MARKER, html)
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
        self.assertIn(IDEA_LABEL, serialized)
        self.assertIn(RISK_LABEL, serialized)
        self.assertIn(SOURCE_MARKER, serialized)
        self.assertNotIn(PRICE_INFO, serialized)
        self.assertNotIn(CONCLUSION, serialized)
        self.assertNotIn(REMOVED_CONCLUSION, serialized)

    def test_llm_prompt_requires_citations_and_omits_conclusion(self) -> None:
        prompt = PROMPT_TEMPLATE.format(company="A Corp", ticker="000001.KS", body="### File: deck.pdf")

        self.assertIn("[\ucd9c\ucc98: file name p.N]", prompt)
        self.assertIn("exactly 3 concise bullet-like lines", prompt)
        self.assertIn('"conclusion": ""', prompt)
        self.assertIn("Do not write a conclusion or checkpoints section.", prompt)


if __name__ == "__main__":
    unittest.main()
