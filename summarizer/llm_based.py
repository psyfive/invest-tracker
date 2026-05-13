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
- Write for developers and investment study members: prioritize numbers, dates, quantities, product names, contracts, margins, capacity, revenue, valuation, and other verifiable facts.
- Avoid vague adjectives such as "strong", "positive", "promising", or "significant" unless the source provides numeric evidence.
- Every summary sentence or bullet line must end with a source marker in this form: [\ucd9c\ucc98: file name/p.N], [\ucd9c\ucc98: file name/Slide N], or [\ucd9c\ucc98: file name].
- For PPT/PDF evidence, preserve the nearest source location from markers such as "### File: name", "--- Slide N ---", and "--- Page N ---".
- Make company overview exactly 3 newline-separated lines in this order:
  1. "\ud575\uc2ec BM: ..." - industry, core products, and target market.
  2. "\uc2dc\uc7a5 \uc9c0\uc704: ..." - market share trend, peer group for valuation comparison, customer relationship, exclusivity, or vendor status if present.
  3. "\uc131\uc7a5 \ubaa8\uba58\ud140: ..." - technical differentiation, profitability, patents, plant completion, mass production, or key schedule over the next 1-2 years if present.
- Each company overview line must be 1-2 factual sentences and end with a source marker. If the source does not mention a required viewpoint, write "\uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c" for that line with the best available source marker.
- Make investment thesis exactly 3 concise bullet-like lines, separated by newlines.
- Make risks exactly 3 concise bullet-like lines, separated by newlines.
- Do not write a conclusion or checkpoints section.
- Return JSON only. Do not wrap it in markdown fences.

{{
  "overview": "Exactly 3 newline-separated Korean lines: \ud575\uc2ec BM, \uc2dc\uc7a5 \uc9c0\uc704, \uc131\uc7a5 \ubaa8\uba58\ud140. Each line is 1-2 factual sentences and ends with [\ucd9c\ucc98: file name/p.N]. Use \uc790\ub8cc \ub0b4 \uba85\uc2dc \uc5c6\uc74c if not present in the source.",
  "thesis": "Investment ideas: exactly 3 upside drivers or catalysts, separated by newlines. Each line is a bullet-style fact summary and ends with a source marker.",
  "risks": "Investment risks: exactly 3 downside or fundamental-damage risks, separated by newlines. Each line is a bullet-style fact summary and ends with a source marker.",
  "conclusion": "",
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
        presentation_month: str = "",
    ) -> Summary:
        if not text or not text.strip():
            return Summary(company=company, ticker=ticker, presenter=presenter, presentation_month=presentation_month)

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
            summary = self._fallback.summarize(text, company, ticker, presenter, presentation_month)
            prefix = f"[LLM call failed; used rule-based fallback: {e}]"
            summary.overview = f"{prefix}\n{summary.overview}" if summary.overview else prefix
            return summary

        return Summary(
            company=company,
            ticker=ticker,
            presenter=presenter,
            presentation_month=presentation_month,
            overview=str(data.get("overview", "")).strip(),
            thesis=str(data.get("thesis", "")).strip(),
            risks=str(data.get("risks", "")).strip(),
            conclusion="",
            target_price=str(data.get("target_price", "")).strip(),
            raw_excerpt=text[:300],
        )
