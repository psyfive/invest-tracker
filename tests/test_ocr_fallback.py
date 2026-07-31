import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from readers import extraction_is_sparse
from summarizer.llm_based import (
    LLMSummarizer,
    _native_text_by_slide,
)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeModels:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    def generate_content(self, model, contents, **kwargs):
        self.calls.append({"model": model, "contents": contents})
        return FakeResponse(self._text)


class FakeClient:
    def __init__(self, text: str) -> None:
        self.models = FakeModels(text)


class ExtractionSparsityTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, size: int) -> Path:
        path = directory / name
        path.write_bytes(b"0" * size)
        return path

    def test_empty_text_from_pdf_is_sparse(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "deck.pdf", 100_000)
            self.assertTrue(extraction_is_sparse(path, ""))

    def test_image_heavy_pptx_is_sparse(self) -> None:
        with TemporaryDirectory() as tmp:
            # 8MB 원본에서 3,000자만 추출된 상황(스피어 케이스와 동일한 비율).
            path = self._write(Path(tmp), "deck.pptx", 8_296_547)
            self.assertTrue(extraction_is_sparse(path, "x" * 3_018))

    def test_text_rich_pptx_is_not_sparse(self) -> None:
        with TemporaryDirectory() as tmp:
            # 352KB 원본에서 39,588자 추출(삼천당제약 케이스).
            path = self._write(Path(tmp), "deck.pptx", 352_392)
            self.assertFalse(extraction_is_sparse(path, "x" * 39_588))

    def test_non_ocr_extensions_are_never_sparse(self) -> None:
        with TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), "notes.txt", 100_000)
            self.assertFalse(extraction_is_sparse(path, ""))


class SlideTextSplitTests(unittest.TestCase):
    def test_native_text_is_grouped_by_slide_marker(self) -> None:
        text = "\n".join(
            [
                "--- Slide 1 ---",
                "표지",
                "",
                "--- Slide 2 ---",
                "목표주가",
                "61,000원",
            ]
        )

        self.assertEqual(_native_text_by_slide(text), {1: "표지", 2: "목표주가\n61,000원"})


class PptxOcrTests(unittest.TestCase):
    def _summarizer(self, client: FakeClient) -> LLMSummarizer:
        summarizer = LLMSummarizer(api_key="test-key")
        summarizer._genai_client = client
        return summarizer

    def test_ocr_merges_native_text_and_keeps_slide_labels(self) -> None:
        client = FakeClient("Base 목표주가 61,000원")
        summarizer = self._summarizer(client)
        native = "--- Slide 1 ---\n한중엔시에스\n\n--- Slide 2 ---\n밸류에이션"
        slides = [(1, [(b"img1", "image/png")]), (2, [(b"img2", "image/png")])]

        with patch("summarizer.llm_based._pptx_slide_images", return_value=slides):
            document = summarizer._read_pptx_via_gemini(Path("deck.pptx"), native)

        body = "\n".join(chunk["text"] for chunk in document.content_block["chunks"])
        self.assertIn("한중엔시에스", body)
        self.assertIn("Base 목표주가 61,000원", body)
        self.assertTrue(all(label.startswith("deck.pptx/Slide") for label in document.block_labels))

    def test_ocr_skips_slides_that_already_have_text(self) -> None:
        client = FakeClient("OCR 결과")
        summarizer = self._summarizer(client)
        summarizer.ocr_slide_text_threshold = 10
        native = "--- Slide 1 ---\n" + ("이미 충분한 텍스트가 있는 슬라이드" * 3) + "\n\n--- Slide 2 ---\n짧음"
        slides = [(1, [(b"img1", "image/png")]), (2, [(b"img2", "image/png")])]

        with patch("summarizer.llm_based._pptx_slide_images", return_value=slides):
            summarizer._read_pptx_via_gemini(Path("deck.pptx"), native)

        self.assertEqual(len(client.models.calls), 1)

    def test_oversized_images_are_skipped(self) -> None:
        client = FakeClient("OCR 결과")
        summarizer = self._summarizer(client)
        slides = [(1, [(b"0" * (8 * 1024 * 1024), "image/png")])]

        with patch("summarizer.llm_based._pptx_slide_images", return_value=slides):
            with self.assertRaises(RuntimeError):
                summarizer._read_pptx_via_gemini(Path("deck.pptx"), "")

        self.assertEqual(client.models.calls, [])

    def test_fallback_uses_ocr_when_extraction_is_sparse(self) -> None:
        client = FakeClient("Base 목표주가 61,000원")
        summarizer = self._summarizer(client)
        slides = [(1, [(b"img1", "image/png")])]

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "deck.pptx"
            path.write_bytes(b"0" * 8_000_000)
            with patch("summarizer.llm_based.read_file", return_value="--- Slide 1 ---\n표지"):
                with patch("summarizer.llm_based._pptx_slide_images", return_value=slides):
                    document, mode = summarizer._read_document_with_ocr_fallback(path)

        self.assertEqual(mode, "ocr")
        body = "\n".join(chunk["text"] for chunk in document.content_block["chunks"])
        self.assertIn("61,000원", body)

    def test_fallback_skips_ocr_when_extraction_is_healthy(self) -> None:
        client = FakeClient("호출되면 안 됨")
        summarizer = self._summarizer(client)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "deck.pptx"
            path.write_bytes(b"0" * 10_000)
            with patch("summarizer.llm_based.read_file", return_value="x" * 50_000):
                document, mode = summarizer._read_document_with_ocr_fallback(path)

        self.assertEqual(mode, "text")
        self.assertEqual(client.models.calls, [])
        self.assertTrue(document.content_block["chunks"])

    def test_fallback_reports_sparse_when_ocr_fails(self) -> None:
        client = FakeClient("")
        summarizer = self._summarizer(client)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "deck.pptx"
            path.write_bytes(b"0" * 8_000_000)
            with patch("summarizer.llm_based.read_file", return_value="--- Slide 1 ---\n표지"):
                with patch("summarizer.llm_based._pptx_slide_images", return_value=[(1, [])]):
                    _document, mode = summarizer._read_document_with_ocr_fallback(path)

        self.assertEqual(mode, "text_sparse")


if __name__ == "__main__":
    unittest.main()
