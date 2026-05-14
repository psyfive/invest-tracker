import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from unittest.mock import patch

from readers.reader import (
    SUPPORTED_EXTS,
    _decompress_hwp_section,
    _extract_hwp_text_from_section,
    iter_supported_files,
    read_file,
)


def _hwp_record(tag_id: int, text: str) -> bytes:
    payload = text.encode("utf-16le")
    header = tag_id | (0 << 10) | (len(payload) << 20)
    return struct.pack("<I", header) + payload


class ReaderTests(unittest.TestCase):
    def test_supported_extensions_include_hwp_and_excel(self) -> None:
        for ext in {".hwp", ".hwpx", ".xlsx", ".xlsm", ".xls"}:
            self.assertIn(ext, SUPPORTED_EXTS)

    def test_iter_supported_files_finds_new_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "report.hwpx"
            ignored = root / "image.png"
            expected.write_text("body", encoding="utf-8")
            ignored.write_text("body", encoding="utf-8")

            files = list(iter_supported_files(root))

        self.assertEqual([p.name for p in files], ["report.hwpx"])

    def test_read_hwpx_extracts_contents_xml_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.hwpx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "Contents/section0.xml",
                    "<root><p><t>Revenue 100</t><t>Margin 20%</t></p></root>",
                )
                archive.writestr("Settings/settings.xml", "<root><t>ignored</t></root>")

            text = read_file(path)

        self.assertIn("--- Section: section0.xml ---", text)
        self.assertIn("Revenue 100", text)
        self.assertIn("Margin 20%", text)
        self.assertNotIn("ignored", text)

    def test_read_xlsx_extracts_sheet_rows(self) -> None:
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl is not installed")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.xlsx"
            workbook = Workbook()
            first = workbook.active
            first.title = "Summary"
            first.append(["Company", "Revenue"])
            first.append(["Alpha", 1200])
            second = workbook.create_sheet("Risks")
            second.append(["Risk", "Delay"])
            workbook.save(path)
            workbook.close()

            text = read_file(path)

        self.assertIn("--- Sheet: Summary ---", text)
        self.assertIn("Company | Revenue", text)
        self.assertIn("Alpha | 1200", text)
        self.assertIn("--- Sheet: Risks ---", text)
        self.assertIn("Risk | Delay", text)

    def test_xls_missing_dependency_mentions_xlrd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.xls"
            path.write_bytes(b"not a real workbook")
            with patch.dict(sys.modules, {"xlrd": None}):
                with self.assertRaisesRegex(RuntimeError, "xlrd is not installed"):
                    read_file(path)

    def test_extract_hwp_text_from_section_reads_para_text_records(self) -> None:
        data = (
            _hwp_record(67, "First line")
            + _hwp_record(10, "ignored")
            + _hwp_record(67, "Second line")
        )

        text = _extract_hwp_text_from_section(data)

        self.assertEqual(text, "First line\nSecond line")

    def test_decompress_hwp_section_handles_raw_deflate(self) -> None:
        data = _hwp_record(67, "Compressed line")
        compressor = zlib.compressobj(wbits=-15)
        compressed = compressor.compress(data) + compressor.flush()

        text = _extract_hwp_text_from_section(_decompress_hwp_section(compressed))

        self.assertEqual(text, "Compressed line")


if __name__ == "__main__":
    unittest.main()
