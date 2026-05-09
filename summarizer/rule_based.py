"""Rule-based summarizer for offline runs."""
from __future__ import annotations

import re

from .base import Summary, Summarizer


SECTION_KEYWORDS: dict[str, list[str]] = {
    "overview": [
        "\uae30\uc5c5\uac1c\uc694",
        "\uae30\uc5c5 \uac1c\uc694",
        "\ud68c\uc0ac\uac1c\uc694",
        "\ud68c\uc0ac \uac1c\uc694",
        "\uc0ac\uc5c5 \uac1c\uc694",
        "\uae30\uc5c5\uc18c\uac1c",
        "\ud68c\uc0ac\uc18c\uac1c",
        "\ube44\uc988\ub2c8\uc2a4 \ubaa8\ub378",
        "\uc0ac\uc5c5 \ubaa8\ub378",
        "company overview",
        "business overview",
        "about",
    ],
    "thesis": [
        "\ud22c\uc790 \uc544\uc774\ub514\uc5b4",
        "\ud22c\uc790\uc544\uc774\ub514\uc5b4",
        "\ud22c\uc790\ud3ec\uc778\ud2b8",
        "\ud22c\uc790 \ud3ec\uc778\ud2b8",
        "\ud22c\uc790 \uadfc\uac70",
        "\uc131\uc7a5 \ub3d9\ub825",
        "\ub9e4\uc218 \uc774\uc720",
        "investment thesis",
        "thesis",
        "catalyst",
        "catalysts",
        "why buy",
    ],
    "risks": [
        "\ud22c\uc790 \ub9ac\uc2a4\ud06c",
        "\ud22c\uc790\ub9ac\uc2a4\ud06c",
        "\ub9ac\uc2a4\ud06c \uc694\uc778",
        "\uc704\ud5d8 \uc694\uc778",
        "\uc8fc\uc694 \ub9ac\uc2a4\ud06c",
        "risk",
        "risks",
        "downside",
    ],
    "target_price": [
        "\ubaa9\ud45c\uc8fc\uac00",
        "\ubaa9\ud45c \uc8fc\uac00",
        "\ubaa9\ud45c\uac00",
        "\ubc38\ub958\uc5d0\uc774\uc158",
        "valuation",
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
            len(tail_low) <= 12 and re.match(r"^[:>\-()\[\]\s.,~]*$", tail_low)
        ):
            return True, ""
        match = re.match(r"^\s*[:>\-]\s*(.+)$", tail)
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
    label = r"(\ubaa9\ud45c\s*\uc8fc\uac00|\ubaa9\ud45c\uac00|target\s*price|price\s*target)"
    pattern_sym = re.compile(
        label + r"\s*[:>\-]?\s*([0-9][0-9,\.]*\s*(?:\uc6d0|KRW|USD|\ub2ec\ub7ec)?)",
        re.IGNORECASE,
    )
    match = pattern_sym.search(text)
    if match:
        return _normalize(match.group(2))

    upside = re.search(r"(\uc0c1\uc2b9\s*\uc5ec\ub825|upside)\s*[:>\-]?\s*([0-9.]+\s*%)", text, re.IGNORECASE)
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
        presentation_month: str = "",
    ) -> Summary:
        if not text or not text.strip():
            return Summary(company=company, ticker=ticker, presenter=presenter, presentation_month=presentation_month)

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
            presentation_month=presentation_month,
            overview=overview,
            thesis=thesis,
            risks=risks,
            target_price=target_price,
            raw_excerpt=_truncate(text, 300),
        )
