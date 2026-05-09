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
- Follow a deep investment report style suitable for a Notion investment-study page.
- Make investment thesis exactly 3 concise bullet-like lines.
- Make risks exactly 3 concise bullet-like lines.
- Return JSON only. Do not wrap it in markdown fences.

{{
  "overview": "Company overview: core business model, products/services, and market position. Write in Korean.",
  "thesis": "Investment ideas: exactly 3 growth drivers or catalysts, separated by newlines. Write in Korean.",
  "risks": "Investment risks: exactly 3 downside or fundamental-damage risks, separated by newlines. Write in Korean.",
  "conclusion": "Conclusion/checkpoints: key items to monitor after the presentation. Write in Korean.",
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
            conclusion=str(data.get("conclusion", "")).strip(),
            target_price=str(data.get("target_price", "")).strip(),
            raw_excerpt=text[:300],
        )
