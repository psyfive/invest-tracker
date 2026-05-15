import json
import unittest
from types import SimpleNamespace

from summarizer.llm_based import (
    LLMSummarizer,
    SourceDocument,
    _annotated_response_text,
    _document_blocks_from_files,
    _documents_prompt_text,
    _match_source_label,
    _prepare_structured_payload,
    _response_metadata,
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

    def test_client_is_reused_across_calls(self) -> None:
        class ReuseSummarizer(LLMSummarizer):
            def __init__(self) -> None:
                self.created = 0
                super().__init__(api_key="test")

            def _client(self):
                if self._genai_client is None:
                    self.created += 1
                    self._genai_client = SimpleNamespace()
                return self._genai_client

        summarizer = ReuseSummarizer()

        first = summarizer._client()
        second = summarizer._client()

        self.assertIs(first, second)
        self.assertEqual(summarizer.created, 1)

    def test_response_metadata_captures_finish_reason_and_usage(self) -> None:
        response = SimpleNamespace(
            candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
            usage_metadata=SimpleNamespace(
                prompt_token_count=120,
                candidates_token_count=80,
                thoughts_token_count=15,
                total_token_count=200,
            ),
        )

        metadata = _response_metadata(response)

        self.assertEqual(metadata["finish_reason"], "MAX_TOKENS")
        self.assertEqual(metadata["usage_metadata"]["prompt_token_count"], 120)
        self.assertEqual(metadata["usage_metadata"]["candidates_token_count"], 80)
        self.assertEqual(metadata["usage_metadata"]["thoughts_token_count"], 15)
        self.assertEqual(metadata["usage_metadata"]["total_token_count"], 200)

    def test_structured_payload_dedupes_similar_facts_and_prefers_presentation_sources(self) -> None:
        payload = {
            "overview": [
                {
                    "fact": "삼성SDI에 ESS 냉각 솔루션을 공급합니다.",
                    "source": "recording.docx/part 1",
                },
                {
                    "fact": "삼성SDI에 ESS 냉각 솔루션을 공급합니다.",
                    "source": "deck.pptx/Slide 3",
                },
            ],
            "thesis": [],
            "risks": [],
            "target_price": [],
        }

        prepared, stats = _prepare_structured_payload(
            payload,
            {"overview": 5, "thesis": 8, "risks": 8},
        )

        self.assertEqual(stats["overview"], {"before_dedupe": 2, "after_dedupe": 1, "after_cap": 1})
        self.assertEqual(prepared["overview"][0]["source"], "deck.pptx/Slide 3")

    def test_structured_payload_caps_items_without_padding_sparse_sections(self) -> None:
        payload = {
            "overview": [
                {"fact": f"개요 {index}", "source": "deck.pptx/Slide 3"}
                for index in range(1, 7)
            ],
            "thesis": [{"fact": "투자 아이디어 1", "source": "deck.pptx/Slide 3"}],
            "risks": [{"fact": "자료 내 명시 없음", "source": ""}],
            "target_price": [],
        }

        prepared, stats = _prepare_structured_payload(
            payload,
            {"overview": 5, "thesis": 8, "risks": 8},
        )

        self.assertEqual(len(prepared["overview"]), 5)
        self.assertEqual(len(prepared["thesis"]), 1)
        self.assertEqual(prepared["risks"], [{"fact": "자료 내 명시 없음", "source": ""}])
        self.assertEqual(stats["overview"]["after_cap"], 5)

    def test_max_tokens_uses_compact_retry_limits(self) -> None:
        class CompactRetrySummarizer(LLMSummarizer):
            def __init__(self) -> None:
                self.prompts: list[str] = []
                self.calls = 0
                super().__init__(
                    api_key="test",
                    max_retries=1,
                    max_items={"overview": 5, "thesis": 8, "risks": 8},
                    compact_retry_max_items={"overview": 3, "thesis": 6, "risks": 6},
                )

            def _call_api(self, _documents, prompt: str) -> str:
                self.calls += 1
                self.prompts.append(prompt)
                if self.calls == 1:
                    self._last_response_metadata = {"finish_reason": "MAX_TOKENS", "usage_metadata": {}}
                    return '{"overview":[{"fact":"긴 개요","source":"deck.pptx/Slide 1"}'
                self._last_response_metadata = {"finish_reason": "STOP", "usage_metadata": {}}
                return json.dumps(
                    {
                        "overview": [
                            {"fact": f"개요 {index}", "source": "deck.pptx/Slide 1"}
                            for index in range(1, 5)
                        ],
                        "thesis": [
                            {"fact": f"아이디어 {index}", "source": "deck.pptx/Slide 1"}
                            for index in range(1, 8)
                        ],
                        "risks": [
                            {"fact": f"리스크 {index}", "source": "deck.pptx/Slide 1"}
                            for index in range(1, 8)
                        ],
                        "target_price": [{"fact": "자료 내 명시 없음", "source": ""}],
                    },
                    ensure_ascii=False,
                )

        document = SourceDocument(
            title="deck.pptx",
            content_block={"chunks": [{"label": "deck.pptx/Slide 1", "text": "body"}]},
            block_labels=["deck.pptx/Slide 1"],
        )
        summarizer = CompactRetrySummarizer()

        summary = summarizer._summarize_documents([document], "A Corp")

        self.assertEqual(summarizer.calls, 2)
        self.assertIn("Stay within these stricter section limits", summarizer.prompts[1])
        self.assertEqual(len(summary.overview.splitlines()), 3)
        self.assertEqual(len(summary.thesis.splitlines()), 6)
        self.assertEqual(len(summary.risks.splitlines()), 6)


if __name__ == "__main__":
    unittest.main()
