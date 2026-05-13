"""Normalize company overview summaries into the required three-line shape."""
from __future__ import annotations

import re


OVERVIEW_LABELS = (
    "\ud575\uc2ec BM",
    "\uc2dc\uc7a5 \uc9c0\uc704",
    "\uc131\uc7a5 \ubaa8\uba58\ud140",
)
NO_INFO = "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c"
SOURCE_RE = re.compile(r"\[(?:\ucd9c\ucc98|source)\s*:", re.IGNORECASE)


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|\d+[\.)]\s+)", "", line).strip()


def _fallback_source_marker(fallback_source: str) -> str:
    source = fallback_source.strip() or "source unavailable"
    return f"[\ucd9c\ucc98: {source}]"


def _ensure_source_marker(line: str, fallback_source: str) -> str:
    if SOURCE_RE.search(line):
        return line
    return f"{line} {_fallback_source_marker(fallback_source)}"


def _split_label(line: str) -> tuple[str | None, str]:
    clean = _strip_bullet_prefix(line)
    for label in OVERVIEW_LABELS:
        pattern = rf"^{re.escape(label)}\s*(?::|-)\s*(.+)$"
        match = re.match(pattern, clean)
        if match:
            return label, match.group(1).strip()
    return None, clean


def normalize_overview_lines(text: str, fallback_source: str = "") -> list[str]:
    """Return exactly three labeled overview lines with source markers."""
    labeled: dict[str, str] = {}
    unlabeled: list[str] = []

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        label, content = _split_label(line)
        if label:
            labeled[label] = content
        elif content:
            unlabeled.append(content)

    lines: list[str] = []
    for index, label in enumerate(OVERVIEW_LABELS):
        content = labeled.get(label)
        if not content and index < len(unlabeled):
            content = unlabeled[index]
        if not content:
            content = NO_INFO

        line = f"{label}: {content}"
        lines.append(_ensure_source_marker(line, fallback_source))
    return lines
