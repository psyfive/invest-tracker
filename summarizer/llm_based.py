"""LLM-backed summarizer using Claude document citations."""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from readers import read_file

from .base import Summary, Summarizer


OVERVIEW_HEADING = "기업 개요"
THESIS_HEADING = "투자 아이디어"
RISKS_HEADING = "투자 리스크"
TARGET_HEADING = "목표가"
SOURCE_RE = re.compile(r"\[(?:출처|source)\s*:", re.IGNORECASE)

SUMMARY_PROMPT = """You are an assistant analyst for a Korean investment study.
Use only the provided documents. Do not infer facts that are not in the materials.

Write in Korean unless the source itself is English-only.
Prefer concrete facts: numbers, dates, quantities, products, customers, contracts,
capacity, revenue, margins, valuation, and explicit schedules.

Return exactly these section headings and no extra sections:

## 기업 개요
- 핵심 BM: ...
- 시장 지위: ...
- 성장 모멘텀: ...

## 투자 아이디어
- ...

## 투자 리스크
- ...

## 목표가
- ...

Rules:
- 기업 개요 should use 핵심 BM, 시장 지위, 성장 모멘텀 when the materials support them.
- If one of those viewpoints is not supported, write "자료 내 명시 없음" for that viewpoint or omit it.
- 투자 아이디어 and 투자 리스크 are not fixed to 3 items. Include only supported items from the materials.
- If no supported investment idea or risk exists, write "자료 내 명시 없음" in that section.
- Every factual bullet or factual sentence must be grounded in document citations.
- Do not mention a source unless the cited document actually supports the claim.
- Do not output JSON or markdown fences.

Company: {company}
Ticker: {ticker}
Presenter: {presenter}
Presentation month: {presentation_month}
"""

REPAIR_PROMPT = """The previous answer failed validation:
{errors}

Rewrite the summary using the same required headings. Keep only claims supported by
the cited documents. Every factual bullet or sentence must have citations.
Do not output JSON or markdown fences.
"""


@dataclass
class SourceDocument:
    title: str
    content_block: dict[str, Any]
    block_labels: list[str]


@dataclass
class CitationText:
    text: str
    citations: list[Any]


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|\d+[\.)]\s+)", "", line).strip()


def _strip_markdown_emphasis(line: str) -> str:
    line = line.strip()
    line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
    line = re.sub(r"__(.+?)__", r"\1", line)
    return line.strip()


def _clean_summary_line(line: str) -> str:
    line = _strip_bullet_prefix(line)
    return _strip_markdown_emphasis(line).strip()


def _heading_key(line: str) -> str:
    line = line.strip()
    line = re.sub(r"^#+\s*", "", line)
    line = _clean_summary_line(line)
    line = line.rstrip(":：").strip()
    normalized = re.sub(r"\s+", "", line)
    if normalized in {"기업개요", "회사개요", "개요"} or normalized.startswith("기업개요"):
        return "overview"
    if "투자아이디어" in normalized or normalized in {"Upside", "투자포인트"}:
        return "thesis"
    if "투자리스크" in normalized or normalized in {"Downside", "리스크"}:
        return "risks"
    if "목표가" in normalized or "목표주가" in normalized or normalized in {"타겟프라이스", "TargetPrice"}:
        return "target_price"
    return ""


def _is_section_heading(line: str) -> bool:
    return bool(_heading_key(line))


def _has_source(line: str) -> bool:
    return bool(SOURCE_RE.search(line))


def _is_no_info(line: str) -> bool:
    return "자료 내 명시 없음" in line or "(empty)" in line


def _is_structural_line(line: str) -> bool:
    raw = line.strip()
    clean = _clean_summary_line(line).strip()
    normalized = re.sub(r"\s+", "", clean.rstrip(":："))
    if not clean or clean in {"---", "***", "___"}:
        return True
    if _is_section_heading(clean):
        return True
    if re.fullmatch(r"\*\*.+?[:：]\*\*", raw):
        return True
    if normalized in {
        "핵심BM",
        "시장지위",
        "성장모멘텀",
        "InvestmentIdea",
        "InvestmentRisk",
    }:
        return True
    if normalized in {"또한", "그리고", "다만", "반면", "한편"}:
        return True
    return False


def _citation_value(citation: Any, name: str, default: Any = None) -> Any:
    if isinstance(citation, dict):
        return citation.get(name, default)
    return getattr(citation, name, default)


def _citation_source(citation: Any, documents: list[SourceDocument]) -> str:
    citation_type = str(_citation_value(citation, "type", ""))
    doc_index = _citation_value(citation, "document_index", None)
    try:
        doc_index_int = int(doc_index)
    except (TypeError, ValueError):
        doc_index_int = -1

    title = str(_citation_value(citation, "document_title", "") or "")
    if 0 <= doc_index_int < len(documents):
        title = title or documents[doc_index_int].title

    if citation_type == "page_location":
        page = _citation_value(citation, "start_page_number", None)
        return f"{title}/p.{page}" if page is not None else title

    if citation_type == "content_block_location":
        block_index = _citation_value(citation, "start_block_index", None)
        try:
            block_index_int = int(block_index)
        except (TypeError, ValueError):
            block_index_int = -1
        if 0 <= doc_index_int < len(documents):
            labels = documents[doc_index_int].block_labels
            if 0 <= block_index_int < len(labels):
                return labels[block_index_int]
        return title

    return title


def _source_marker(citations: list[Any], documents: list[SourceDocument]) -> str:
    sources: list[str] = []
    for citation in citations:
        source = _citation_source(citation, documents).strip()
        if source and source not in sources:
            sources.append(source)
    if not sources:
        return ""
    return f"[출처: {'; '.join(sources)}]"


def _line_with_marker(line: str, marker: str) -> str:
    stripped = line.strip()
    if not stripped or _is_section_heading(stripped) or _has_source(stripped) or not marker:
        return stripped
    return f"{stripped} {marker}"


def _message_text_blocks(message: Any) -> list[CitationText]:
    blocks: list[CitationText] = []
    for block in getattr(message, "content", []) or []:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if not text:
            continue
        citations = getattr(block, "citations", None)
        if citations is None and isinstance(block, dict):
            citations = block.get("citations")
        blocks.append(CitationText(text=str(text), citations=list(citations or [])))
    return blocks


def _annotated_response_text(message: Any, documents: list[SourceDocument]) -> str:
    lines: list[str] = []
    for block in _message_text_blocks(message):
        marker = _source_marker(block.citations, documents)
        for raw in block.text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                lines.append("")
            else:
                lines.append(_line_with_marker(line, marker))
    return "\n".join(lines).strip()


def parse_summary_markdown(
    text: str,
    company: str,
    ticker: str = "",
    presenter: str = "",
    presentation_month: str = "",
) -> Summary:
    sections: dict[str, list[str]] = {
        "overview": [],
        "thesis": [],
        "risks": [],
        "target_price": [],
    }
    current = ""

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = _heading_key(line)
        if key:
            current = key
            continue
        if not current:
            continue
        if _is_structural_line(line):
            continue
        sections[current].append(_clean_summary_line(line))

    return Summary(
        company=company,
        ticker=ticker,
        presenter=presenter,
        presentation_month=presentation_month,
        overview="\n".join(sections["overview"]).strip(),
        thesis="\n".join(sections["thesis"]).strip(),
        risks="\n".join(sections["risks"]).strip(),
        conclusion="",
        target_price="\n".join(sections["target_price"]).strip(),
        raw_excerpt=text[:300],
    )


def validate_cited_summary(summary: Summary) -> list[str]:
    errors: list[str] = []
    if not (summary.overview or summary.thesis or summary.risks):
        errors.append("요약 본문이 비어 있습니다.")

    for section_name, body in [
        ("기업 개요", summary.overview),
        ("투자 아이디어", summary.thesis),
        ("투자 리스크", summary.risks),
    ]:
        for line in body.splitlines():
            line = line.strip()
            if not line or _is_no_info(line) or _is_structural_line(line):
                continue
            if not _has_source(line):
                errors.append(f"{section_name} 항목에 출처가 없습니다: {line}")

    target = summary.target_price.strip()
    if target and not _is_no_info(target) and not _is_structural_line(target) and not _has_source(target):
        errors.append(f"목표가 항목에 출처가 없습니다: {target}")
    return errors


def _safe_debug_name(company: str, ticker: str) -> str:
    base = "_".join(part for part in [company, ticker] if part).strip() or "llm_summary"
    base = re.sub(r"[\\/:*?\"<>|\s]+", "_", base)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{base}_{stamp}.json"


def _read_pdf_block(path: Path) -> SourceDocument:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return SourceDocument(
        title=path.name,
        block_labels=[],
        content_block={
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": data,
            },
            "title": path.name,
            "citations": {"enabled": True},
        },
    )


def _marker_label(path: Path, marker: str, part_index: int = 1) -> str:
    marker = marker.strip()
    match = re.match(r"^---\s*(Slide|Page|Section)\s*:\s*(.+?)\s*---$", marker, flags=re.IGNORECASE)
    if match:
        return f"{path.name}/{match.group(1).title()} {match.group(2)}"
    match = re.match(r"^---\s*(Slide|Page|Section)\s+(.+?)\s*---$", marker, flags=re.IGNORECASE)
    if match:
        return f"{path.name}/{match.group(1).title()} {match.group(2)}"
    match = re.match(r"^---\s*Sheet:\s*(.+?)\s*---$", marker, flags=re.IGNORECASE)
    if match:
        return f"{path.name}/Sheet {match.group(1)}"
    return f"{path.name}/part {part_index}"


def _split_text_chunks(path: Path, text: str, max_chars: int = 3500) -> tuple[list[dict[str, str]], list[str]]:
    chunks: list[dict[str, str]] = []
    labels: list[str] = []
    current_label = f"{path.name}/part 1"
    current_lines: list[str] = []
    part_index = 1

    def flush() -> None:
        nonlocal part_index, current_lines, current_label
        body = "\n".join(current_lines).strip()
        if not body:
            current_lines = []
            return
        while len(body) > max_chars:
            piece = body[:max_chars].rstrip()
            chunks.append({"type": "text", "text": f"[{current_label}]\n{piece}"})
            labels.append(current_label)
            body = body[max_chars:].lstrip()
            part_index += 1
            current_label = f"{path.name}/part {part_index}"
        if body:
            chunks.append({"type": "text", "text": f"[{current_label}]\n{body}"})
            labels.append(current_label)
        current_lines = []

    for raw in text.splitlines():
        line = raw.rstrip()
        if re.match(r"^---\s*(?:Slide|Page|Section|Sheet:)", line, flags=re.IGNORECASE):
            flush()
            part_index += 1
            current_label = _marker_label(path, line, part_index)
            continue
        current_lines.append(line)
    flush()

    if not chunks and text.strip():
        chunks.append({"type": "text", "text": f"[{path.name}]\n{text.strip()}"})
        labels.append(path.name)
    return chunks, labels


def _read_text_document(path: Path, text: str | None = None) -> SourceDocument:
    body = text if text is not None else read_file(path)
    chunks, labels = _split_text_chunks(path, body)
    if not chunks:
        raise RuntimeError("no extractable text")
    return SourceDocument(
        title=path.name,
        block_labels=labels,
        content_block={
            "type": "document",
            "source": {
                "type": "content",
                "content": chunks,
            },
            "title": path.name,
            "context": "Each content block starts with a source label that identifies file and slide/page/sheet/part.",
            "citations": {"enabled": True},
        },
    )


def _document_blocks_from_files(file_paths: list[Path]) -> list[SourceDocument]:
    documents: list[SourceDocument] = []
    failures: list[str] = []
    for path in file_paths:
        try:
            if path.suffix.lower() == ".pdf":
                documents.append(_read_pdf_block(path))
            else:
                documents.append(_read_text_document(path))
        except Exception as e:
            failures.append(f"{path.name}: {e}")
            continue
    if not documents and failures:
        raise RuntimeError("no readable source files for LLM summarization: " + "; ".join(failures))
    return documents


class LLMSummarizer(Summarizer):
    """Anthropic Claude API summarizer with document citations."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-6",
        api_key: str | None = None,
        max_tokens: int = 3000,
        max_retries: int = 1,
        debug_dir: str | Path | None = None,
        fallback_on_error: bool = False,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.fallback_on_error = fallback_on_error

    def _client(self) -> Any:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic is not installed; run pip install anthropic") from e

        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        return Anthropic(api_key=self.api_key)

    def _call_api(self, documents: list[SourceDocument], prompt: str) -> Any:
        content = [doc.content_block for doc in documents]
        content.append({"type": "text", "text": prompt})
        return self._client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": content}],
        )

    def _write_debug(
        self,
        company: str,
        ticker: str,
        response_text: str,
        errors: list[str],
        documents: list[SourceDocument],
    ) -> None:
        if self.debug_dir is None:
            return
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "company": company,
            "ticker": ticker,
            "model": self.model,
            "errors": errors,
            "response_text": response_text,
            "documents": [
                {"title": doc.title, "block_labels": doc.block_labels}
                for doc in documents
            ],
        }
        path = self.debug_dir / _safe_debug_name(company, ticker)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _summarize_documents(
        self,
        documents: list[SourceDocument],
        company: str,
        ticker: str = "",
        presenter: str = "",
        presentation_month: str = "",
    ) -> Summary:
        prompt = SUMMARY_PROMPT.format(
            company=company,
            ticker=ticker or "unknown ticker",
            presenter=presenter or "-",
            presentation_month=presentation_month or "-",
        )

        response_text = ""
        errors: list[str] = []
        for attempt in range(self.max_retries + 1):
            call_prompt = prompt if attempt == 0 else REPAIR_PROMPT.format(errors="\n".join(errors))
            message = self._call_api(documents, call_prompt)
            response_text = _annotated_response_text(message, documents)
            summary = parse_summary_markdown(
                response_text,
                company=company,
                ticker=ticker,
                presenter=presenter,
                presentation_month=presentation_month,
            )
            errors = validate_cited_summary(summary)
            if not errors:
                return summary

        self._write_debug(company, ticker, response_text, errors, documents)
        raise RuntimeError("LLM summary failed citation validation: " + "; ".join(errors))

    def summarize_files(
        self,
        file_paths: list[str | Path],
        company: str,
        ticker: str = "",
        presenter: str = "",
        presentation_month: str = "",
    ) -> Summary:
        paths = [Path(path).resolve() for path in file_paths if Path(path).exists()]
        if not paths:
            raise RuntimeError("no existing source files for LLM summarization")
        documents = _document_blocks_from_files(paths)
        return self._summarize_documents(documents, company, ticker, presenter, presentation_month)

    def summarize(
        self,
        text: str,
        company: str,
        ticker: str = "",
        presenter: str = "",
        presentation_month: str = "",
    ) -> Summary:
        if not text or not text.strip():
            return Summary(company=company, ticker=ticker, presenter=presenter, presentation_month=presentation_month)
        document = _read_text_document(Path("source.txt"), text)
        return self._summarize_documents([document], company, ticker, presenter, presentation_month)
