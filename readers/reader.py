"""Extract text from presentation/source files."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


SUPPORTED_EXTS = {".pptx", ".pdf", ".docx", ".txt", ".md"}


def _read_pptx(path: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(path))
    chunks: list[str] = []
    for i, slide in enumerate(prs.slides, start=1):
        slide_texts: list[str] = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in para.runs).strip()
                    if line:
                        slide_texts.append(line)

            if getattr(shape, "has_table", False):
                try:
                    for row in shape.table.rows:
                        for cell in row.cells:
                            text = cell.text.strip()
                            if text:
                                slide_texts.append(text)
                except (AttributeError, ValueError):
                    pass

        if slide.has_notes_slide:
            note_text = slide.notes_slide.notes_text_frame.text.strip()
            if note_text:
                slide_texts.append(f"[notes] {note_text}")

        if slide_texts:
            chunks.append(f"--- Slide {i} ---\n" + "\n".join(slide_texts))
    return "\n\n".join(chunks)


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    chunks: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        text = text.strip()
        if text:
            chunks.append(f"--- Page {i} ---\n{text}")
    return "\n\n".join(chunks)


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []
    for para in doc.paragraphs:
        line = para.text.strip()
        if line:
            parts.append(line)

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _read_text(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def read_file(path: str | Path) -> str:
    """Read a supported file and return extracted text."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")

    ext = p.suffix.lower()
    if ext == ".pptx":
        return _read_pptx(p)
    if ext == ".pdf":
        return _read_pdf(p)
    if ext == ".docx":
        return _read_docx(p)
    if ext in {".txt", ".md"}:
        return _read_text(p)
    return ""


def read_directory(directory: str | Path) -> dict[str, str]:
    """Read every supported file in a directory."""
    d = Path(directory)
    if not d.is_dir():
        raise NotADirectoryError(f"not a directory: {d}")
    out: dict[str, str] = {}
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            try:
                out[p.name] = read_file(p)
            except Exception as e:
                out[p.name] = f"[read failed: {e}]"
    return out


def iter_supported_files(directory: str | Path) -> Iterable[Path]:
    d = Path(directory)
    for p in sorted(d.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            yield p
