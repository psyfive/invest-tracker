"""Classify companies into the study's standard sector taxonomy."""
from __future__ import annotations

import json
import os
import re


SECTOR_TAXONOMY: dict[str, str] = {
    "\uc5d0\ub108\uc9c0": "\uc5d0\ub108\uc9c0 \uc124\ube44 \ubc0f \uc11c\ube44\uc2a4, \uc11d\uc720 \ubc0f \uac00\uc2a4",
    "\uc18c\uc7ac": "\ud654\ud559, \ucca0\uac15, \uae08\uc18d \ubc0f \uad11\uc5c5, \uac74\ucd95\uc790\uc7ac, \ud3ec\uc7a5\uc7ac",
    "\uc0b0\uc5c5\uc7ac": "\uac74\uc124, \uae30\uacc4, \uc870\uc120, \ud56d\uacf5\uc6b4\uc1a1, \uc721\uc0c1\uc6b4\uc1a1, \uc804\uae30\uc7a5\ube44, \uc0c1\uc5c5\uc11c\ube44\uc2a4",
    "\uacbd\uae30\uad00\ub828\uc18c\ube44\uc7ac": "\uc790\ub3d9\ucc28 \ubc0f \ubd80\ud488, \ud638\ud154/\ub808\uc800, \uc12c\uc720/\uc758\ub958/\uc2e0\ubc1c, \ud654\uc7a5\ud488, \uc18c\ub9e4(\uc720\ud1b5)",
    "\ud544\uc218\uc18c\ube44\uc7ac": "\uc74c\uc2dd\ub8cc, \ub2f4\ubc30, \uac00\uc815\uc6a9\ud488, \uac1c\uc778\uc6a9\ud488",
    "\uac74\uac15\uad00\ub9ac": "\uc81c\uc57d, \uc0dd\ubb3c\uacf5\ud559(\ubc14\uc774\uc624), \uc758\ub8cc \uae30\uae30 \ubc0f \uc11c\ube44\uc2a4",
    "\uae08\uc735": "\uc740\ud589, \uc99d\uad8c, \ubcf4\ud5d8, \ub2e4\uac01\ud654\ub41c \uae08\uc735",
    "IT (\uc815\ubcf4\uae30\uc220)": "\ubc18\ub3c4\uccb4, \ud558\ub4dc\uc6e8\uc5b4, \uc18c\ud504\ud2b8\uc6e8\uc5b4, IT \uc11c\ube44\uc2a4, \uc804\uc790\uc7a5\ube44",
    "\ucee4\ubba4\ub2c8\ucf00\uc774\uc158 \uc11c\ube44\uc2a4": "\ud1b5\uc2e0\uc11c\ube44\uc2a4, \ubbf8\ub514\uc5b4, \uc5d4\ud130\ud14c\uc778\uba3c\ud2b8, \uc591\ubc29\ud5a5 \ubbf8\ub514\uc5b4",
    "\uc720\ud2f8\ub9ac\ud2f0": "\uc804\uae30, \uac00\uc2a4, \uc218\ub3c4",
}

VALID_SECTORS = tuple(SECTOR_TAXONOMY.keys())


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _truncate_for_prompt(text: str, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n...[middle omitted]...\n\n{tail}"


def _normalize_sector_values(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        values = []

    sectors: list[str] = []
    for sector in values:
        sector = sector.strip()
        if sector in SECTOR_TAXONOMY and sector not in sectors:
            sectors.append(sector)
    return sectors


def parse_sector_response(text: str) -> list[str]:
    """Return valid sectors from an LLM response, or an empty list."""
    raw = _strip_code_fence(text)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {"sectors": [raw.strip()]}

    if not isinstance(data, dict):
        return []
    if "sectors" in data:
        return _normalize_sector_values(data["sectors"])
    return _normalize_sector_values(data.get("sector", ""))


def build_sector_prompt(company: str, ticker: str = "", body: str = "") -> str:
    taxonomy = "\n".join(
        f"- {sector}: {industries}"
        for sector, industries in SECTOR_TAXONOMY.items()
    )
    sectors = ", ".join(VALID_SECTORS)
    return f"""You classify public companies for a Korean investment study database.
Choose every materially relevant sector from the allowed sector list.

Rules:
- Return 1 to 3 sectors. Use more than one only when the company has meaningful business exposure in multiple sectors.
- Put the main revenue/business exposure first when multiple sectors are returned.
- Use the industry group descriptions as classification guidance.
- Return JSON only. Do not wrap it in markdown fences.
- Every value in "sectors" must be exactly one of: {sectors}

Allowed sectors and included industry groups:
{taxonomy}

Company: {company or "unknown"}
Ticker: {ticker or "unknown"}

[SOURCE START]
{_truncate_for_prompt(body)}
[SOURCE END]

Return this exact JSON shape:
{{"sectors": ["one allowed sector"]}}
"""


class SectorClassifier:
    """Anthropic-backed sector classifier."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        api_key: str | None = None,
        max_tokens: int = 120,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens

    def _call_api(self, prompt: str) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic is not installed; run pip install anthropic") from e

        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

        client = Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        parts: list[str] = []
        for block in msg.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "".join(parts)

    def classify(self, company: str, ticker: str = "", body: str = "") -> list[str]:
        prompt = build_sector_prompt(company=company, ticker=ticker, body=body)
        return parse_sector_response(self._call_api(prompt))
