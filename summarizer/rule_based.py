"""Rule-based summarizer for offline runs."""
from __future__ import annotations

import re

from .base import Summary, Summarizer


SECTION_KEYWORDS: dict[str, list[str]] = {
    "overview": [
        "기업개요",
        "회사개요",
        "회사 개요",
        "기업 개요",
        "사업 개요",
        "기업소개",
        "회사소개",
        "비즈니스 모델",
        "사업 모델",
        "company overview",
        "business overview",
        "about",
    ],
    "thesis": [
        "투자 아이디어",
        "투자아이디어",
        "투자포인트",
        "투자 포인트",
        "투자 근거",
        "성장 동력",
        "매수 이유",
        "investment thesis",
        "thesis",
        "catalyst",
        "catalysts",
        "why buy",
    ],
    "risks": [
        "투자 리스크",
        "투자리스크",
        "리스크 요인",
        "위험 요인",
        "주요 리스크",
        "risk",
        "risks",
        "downside",
    ],
    "target_price": [
        "목표주가",
        "목표 주가",
        "목표가",
        "valuation",
        "밸류에이션",
        "price target",
        "target price",
    ],
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_header(line: str, keyword: str) -> tuple[bool, str]:
    stripped = re.sub(r"^[\s\W\d_]+", "", line).strip()
    low = stripped.lower()
    kw = keyword.lower()

    if low == kw:
        return True, ""

    if low.startswith(kw):
        tail = stripped[len(keyword) :]
        tail_low = tail.lower().strip()
        if not tail_low or (
            len(tail_low) <= 12 and re.match(r"^[:：\-()\[\]\s.,~]*$", tail_low)
        ):
            return True, ""
        match = re.match(r"^\s*[:：]\s*(.+)$", tail)
        if match:
            return True, match.group(1).strip()

    if len(low) <= 40 and keyword.isascii():
        if re.search(r"(?i)\b" + re.escape(keyword) + r"\b", low):
            return True, ""

    return False, ""


def _find_sections(text: str) -> dict[str, str]:
    lines = text.splitlines()
    markers: list[tuple[int, str, str]] = []

    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line or len(line) > 100:
            continue

        for key, keywords in SECTION_KEYWORDS.items():
            for keyword in keywords:
                ok, inline = _looks_like_header(line, keyword)
                if ok:
                    markers.append((i, key, inline))
                    break
            if markers and markers[-1][0] == i:
                break

    if not markers:
        return {}

    seen: set[str] = set()
    filtered: list[tuple[int, str, str]] = []
    for marker in markers:
        if marker[1] in seen:
            continue
        seen.add(marker[1])
        filtered.append(marker)
    filtered.sort()

    sections: dict[str, str] = {}
    for idx, (line_idx, key, inline_body) in enumerate(filtered):
        end = filtered[idx + 1][0] if idx + 1 < len(filtered) else len(lines)
        kept: list[str] = []
        if inline_body:
            kept.append(inline_body)

        for line in lines[line_idx + 1 : end]:
            line = line.strip()
            if not line:
                continue
            if re.match(r"^---\s*(Slide|Page)\s*\d+\s*---\s*$", line):
                continue
            kept.append(line)

        body = "\n".join(kept)
        if body:
            sections[key] = body
    return sections


def _extract_target_price(text: str) -> str:
    label = r"(목표\s*주가|목표가|target\s*price|price\s*target)"
    pattern_sym = re.compile(
        label + r"\s*[:：]?\s*([₩$€£¥]?\s*[0-9][0-9,\.]*\s*(?:원|KRW|USD|달러)?)",
        re.IGNORECASE,
    )
    match = pattern_sym.search(text)
    if match:
        return _normalize(match.group(2))

    upside = re.search(r"(상승\s*여력|upside)\s*[:：]?\s*([0-9.]+\s*%)", text, re.IGNORECASE)
    if upside:
        return f"{upside.group(1)} {upside.group(2)}"
    return ""


def _truncate(text: str, max_chars: int = 600) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


class RuleBasedSummarizer(Summarizer):
    """Extract sections by common Korean/English headings."""

    def __init__(self, max_section_chars: int = 600) -> None:
        self.max_section_chars = max_section_chars

    def summarize(
        self,
        text: str,
        company: str,
        ticker: str = "",
        presenter: str = "",
    ) -> Summary:
        if not text or not text.strip():
            return Summary(company=company, ticker=ticker, presenter=presenter)

        sections = _find_sections(text)
        overview = _truncate(sections.get("overview", ""), self.max_section_chars)
        thesis = _truncate(sections.get("thesis", ""), self.max_section_chars)
        risks = _truncate(sections.get("risks", ""), self.max_section_chars)

        target_price = sections.get("target_price", "").strip()
        if target_price:
            target_price = _truncate(target_price, 200)
        else:
            target_price = _extract_target_price(text)

        if not (overview or thesis or risks):
            overview = _truncate(_normalize(text), self.max_section_chars)

        return Summary(
            company=company,
            ticker=ticker,
            presenter=presenter,
            overview=overview,
            thesis=thesis,
            risks=risks,
            target_price=target_price,
            raw_excerpt=_truncate(text, 300),
        )
