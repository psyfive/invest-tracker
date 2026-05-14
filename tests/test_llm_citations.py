import unittest
from types import SimpleNamespace

from summarizer.llm_based import (
    SourceDocument,
    _annotated_response_text,
    _document_blocks_from_files,
    parse_summary_markdown,
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


if __name__ == "__main__":
    unittest.main()
