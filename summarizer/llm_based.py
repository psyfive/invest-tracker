"""LLM-backed summarizer with rule-based fallback."""
from __future__ import annotations

import json
import os
import re

from .base import Summary, Summarizer
from .rule_based import RuleBasedSummarizer


PROMPT_TEMPLATE = """You are an assistant analyst for Korean stock study notes.
Read the presentation text below and summarize {company} ({ticker}) into this exact JSON schema.

Rules:
- Use only information present in the source text.
- Write Korean unless the source itself is English-only.
- Use short, useful paragraphs or bullet-like sentences.
- Return JSON only. Do not wrap it in markdown fences.

{{
  "overview": "Company overview, business model, products/services, market position.",
  "thesis": "Investment thesis, growth drivers, catalysts, reasons to buy.",
  "risks": "Macro, industry, company-specific, valuation, or execution risks.",
  "target_price": "Target price or upside, including unit, if present."
}}

[SOURCE START]
{body}
[SOURCE END]
"""


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.+?)\s*```$", text, flags=re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def _truncate_for_prompt(text: str, max_chars: int = 18000) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n\n...[middle omitted]...\n\n{tail}"


class LLMSummarizer(Summarizer):
    """Anthropic Claude API summarizer."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-5",
        api_key: str | None = None,
        max_tokens: int = 1500,
        fallback_on_error: bool = True,
    ) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self.fallback_on_error = fallback_on_error
        self._fallback = RuleBasedSummarizer()

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

    def summarize(
        self,
        text: str,
        company: str,
        ticker: str = "",
        presenter: str = "",
    ) -> Summary:
        if not text or not text.strip():
            return Summary(company=company, ticker=ticker, presenter=presenter)

        prompt = PROMPT_TEMPLATE.format(
            company=company,
            ticker=ticker or "unknown ticker",
            body=_truncate_for_prompt(text),
        )

        try:
            raw = self._call_api(prompt)
            data = json.loads(_strip_code_fence(raw))
        except Exception as e:
            if not self.fallback_on_error:
                raise
            summary = self._fallback.summarize(text, company, ticker, presenter)
            prefix = f"[LLM call failed; used rule-based fallback: {e}]"
            summary.overview = f"{prefix}\n{summary.overview}" if summary.overview else prefix
            return summary

        return Summary(
            company=company,
            ticker=ticker,
            presenter=presenter,
            overview=str(data.get("overview", "")).strip(),
            thesis=str(data.get("thesis", "")).strip(),
            risks=str(data.get("risks", "")).strip(),
            target_price=str(data.get("target_price", "")).strip(),
            raw_excerpt=text[:300],
        )
