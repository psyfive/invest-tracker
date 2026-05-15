import unittest
from types import SimpleNamespace

from summarizer.llm_based import (
    LLMSummarizer,
    SourceDocument,
    _annotated_response_text,
    _document_blocks_from_files,
    _documents_prompt_text,
    _match_source_label,
    parse_summary_markdown,
    structured_payload_to_summary,
    validate_cited_summary,
)


SOURCE = "[\ucd9c\ucc98: deck.pptx/Slide 3]"


class LLMCitationSummaryTests(unittest.TestCase):
    def test_parse_summary_allows_variable_item_counts(self) -> None:
        text = "\n".join(
            [
                "## \uae30\uc5c5 \uac1c\uc694",
                f"- \ud575\uc2ec BM: ESS \ub0c9\uac01 \ubd80\ud488 {SOURCE}",
                "- \uc2dc\uc7a5 \uc9c0\uc704: \uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c",
                "## \ud22c\uc790 \uc544\uc774\ub514\uc5b4",
                f"- \uc591\uc0b0 \uc77c\uc815 \uad6c\uccb4\ud654 {SOURCE}",
                f"- \uace0\uac1d\uc0ac \ud655\ub300 {SOURCE}",
                "## \ud22c\uc790 \ub9ac\uc2a4\ud06c",
                f"- \ubc1c\uc8fc \uc9c0\uc5f0 \uc704\ud5d8 {SOURCE}",
                "## \ubaa9\ud45c\uac00",
                "- \uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c",
            ]
        )

        summary = parse_summary_markdown(text, company="A Corp", ticker="000001.KS")

        self.assertEqual(len(summary.thesis.splitlines()), 2)
        self.assertEqual(len(summary.risks.splitlines()), 1)
        self.assertEqual(validate_cited_summary(summary), [])

    def test_validation_rejects_uncited_factual_lines(self) -> None:
        summary = parse_summary_markdown(
            "\n".join(
                [
                    "## \uae30\uc5c5 \uac1c\uc694",
                    "- \ud575\uc2ec BM: ESS \ub0c9\uac01 \ubd80\ud488",
                    "## \ud22c\uc790 \uc544\uc774\ub514\uc5b4",
                    "- \uc591\uc0b0 \uc77c\uc815 \uad6c\uccb4\ud654",
                    "## \ud22c\uc790 \ub9ac\uc2a4\ud06c",
                    "- \uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c",
                ]
            ),
            company="A Corp",
        )

        errors = validate_cited_summary(summary)

        self.assertGreaterEqual(len(errors), 2)

    def test_validation_ignores_markdown_labels_and_rule_lines(self) -> None:
        summary = parse_summary_markdown(
            "\n".join(
                [
                    "## \uae30\uc5c5 \uac1c\uc694",
                    "- **\ud575\uc2ec BM:**",
                    f"- ESS \ub0c9\uac01 \ubd80\ud488 {SOURCE}",
                    "---",
                    "## \ud22c\uc790 \uc544\uc774\ub514\uc5b4",
                    "- **\uc591\uc0b0 \uc77c\uc815:**",
                    "- **\uc0bc\uc131SDI \ubd81\ubbf8 \ub77c\uc778 \uac00\ub3d9\uc5d0 \ub530\ub978 Q \ud655\uc815\uc131:**",
                    f"- \uc591\uc0b0 \uc77c\uc815 \uad6c\uccb4\ud654 {SOURCE}",
                    "## \ubaa9\ud45c \uc8fc\uac00 \ubc0f \uacb0\ub860",
                    "- \uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c",
                ]
            ),
            company="A Corp",
        )

        self.assertEqual(validate_cited_summary(summary), [])

    def test_content_block_citation_is_rendered_as_source_marker(self) -> None:
        documents = [
            SourceDocument(
                title="deck.pptx",
                content_block={},
                block_labels=["deck.pptx/Slide 1", "deck.pptx/Slide 3"],
            )
        ]
        citation = SimpleNamespace(
            type="content_block_location",
            document_index=0,
            document_title="deck.pptx",
            start_block_index=1,
            end_block_index=2,
        )
        message = SimpleNamespace(
            content=[
                SimpleNamespace(
                    type="text",
                    text="- \uc591\uc0b0 \uc77c\uc815 \uad6c\uccb4\ud654",
                    citations=[citation],
                )
            ]
        )

        text = _annotated_response_text(message, documents)

        self.assertEqual(text, f"- \uc591\uc0b0 \uc77c\uc815 \uad6c\uccb4\ud654 {SOURCE}")

    def test_unreadable_optional_files_are_skipped_when_other_documents_exist(self) -> None:
        class BadPath:
            name = "bad.xlsx"
            suffix = ".xlsx"

        class GoodPath:
            name = "notes.txt"
            suffix = ".txt"

        def fake_read_file(path):
            if path.name == "bad.xlsx":
                raise RuntimeError("openpyxl is not installed")
            return "body"

        import summarizer.llm_based as llm_based

        original = llm_based.read_file
        try:
            llm_based.read_file = fake_read_file
            docs = _document_blocks_from_files([BadPath(), GoodPath()])
        finally:
            llm_based.read_file = original

        self.assertEqual([doc.title for doc in docs], ["notes.txt"])

    def test_structured_payload_is_converted_to_existing_summary_contract(self) -> None:
        payload = {
            "overview": [
                {"fact": "\ud575\uc2ec BM: ESS \ub0c9\uac01 \ubd80\ud488", "source": "deck.pptx/Slide 3"},
                {"fact": "\uc2dc\uc7a5 \uc9c0\uc704: \uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""},
            ],
            "thesis": [{"fact": "\uc591\uc0b0 \uc77c\uc815 \uad6c\uccb4\ud654", "source": "deck.pptx/Slide 3"}],
            "risks": [{"fact": "\ubc1c\uc8fc \uc9c0\uc5f0 \uc704\ud5d8", "source": "deck.pptx/Slide 3"}],
            "target_price": [{"fact": "\ubaa9\ud45c\uc8fc\uac00 95,000\uc6d0", "source": "deck.pptx/Slide 3"}],
        }

        summary, errors = structured_payload_to_summary(
            payload,
            allowed_labels=["deck.pptx/Slide 3"],
            company="A Corp",
            ticker="000001.KS",
        )

        self.assertEqual(errors, [])
        self.assertIn(SOURCE, summary.overview)
        self.assertIn(SOURCE, summary.thesis)
        self.assertIn(SOURCE, summary.risks)
        self.assertIn(SOURCE, summary.target_price)

    def test_structured_payload_rejects_missing_factual_source(self) -> None:
        payload = {
            "overview": [{"fact": "\ud575\uc2ec BM: ESS \ub0c9\uac01 \ubd80\ud488", "source": ""}],
            "thesis": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
            "risks": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
            "target_price": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
        }

        _summary, errors = structured_payload_to_summary(
            payload,
            allowed_labels=["deck.pptx/Slide 3"],
            company="A Corp",
        )

        self.assertTrue(any("\ucd9c\ucc98" in error for error in errors))

    def test_no_info_items_do_not_need_sources(self) -> None:
        payload = {
            "overview": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
            "thesis": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
            "risks": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
            "target_price": [{"fact": "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c", "source": ""}],
        }

        _summary, errors = structured_payload_to_summary(
            payload,
            allowed_labels=["deck.pptx/Slide 3"],
            company="A Corp",
        )

        self.assertEqual(errors, [])

    def test_source_label_canonical_matching_accepts_common_variants(self) -> None:
        allowed = ["deck.pptx/Slide 3"]

        self.assertEqual(_match_source_label("deck.pptx/Slide3", allowed), ("deck.pptx/Slide 3", ""))
        self.assertEqual(_match_source_label("deck.pptx/\uc2ac\ub77c\uc774\ub4dc 3", allowed), ("deck.pptx/Slide 3", ""))

    def test_ambiguous_fuzzy_source_is_rejected(self) -> None:
        matched, error = _match_source_label(
            "deck.pptx/Slide",
            ["deck.pptx/Slide 1", "deck.pptx/Slide 2"],
        )

        self.assertEqual(matched, "")
        self.assertIn("\uc560\ub9e4", error)

    def test_source_blocks_use_explicit_start_and_end_boundaries(self) -> None:
        document = SourceDocument(
            title="deck.pptx",
            content_block={
                "chunks": [
                    {"label": "deck.pptx/Slide 1", "text": "\ubcf8\ubb38"},
                ]
            },
            block_labels=["deck.pptx/Slide 1"],
        )

        text = _documents_prompt_text([document])

        self.assertIn("--- BLOCK START: [deck.pptx/Slide 1] ---", text)
        self.assertIn("--- BLOCK END: [deck.pptx/Slide 1] ---", text)

    def test_retryable_gemini_errors_use_exponential_backoff(self) -> None:
        class RateLimitError(Exception):
            code = 429

        class RetrySummarizer(LLMSummarizer):
            def __init__(self) -> None:
                self.calls = 0
                self.sleeps: list[float] = []
                super().__init__(api_key="test", api_retries=2, sleep_func=self.sleeps.append)

            def _client(self):
                return SimpleNamespace(
                    models=SimpleNamespace(generate_content=self._generate_content)
                )

            def _generate_content(self, **_kwargs):
                self.calls += 1
                if self.calls < 3:
                    raise RateLimitError("429 Too Many Requests")
                return SimpleNamespace(text='{"overview":[],"thesis":[],"risks":[],"target_price":[]}')

        document = SourceDocument(
            title="notes.txt",
            content_block={"chunks": [{"label": "notes.txt/part 1", "text": "body"}]},
            block_labels=["notes.txt/part 1"],
        )
        summarizer = RetrySummarizer()

        result = summarizer._call_api([document], "prompt")

        self.assertIn('"overview"', result)
        self.assertEqual(summarizer.calls, 3)
        self.assertEqual(len(summarizer.sleeps), 2)
        self.assertGreaterEqual(summarizer.sleeps[0], 1)
        self.assertGreaterEqual(summarizer.sleeps[1], 2)


if __name__ == "__main__":
    unittest.main()
