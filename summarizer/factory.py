"""Create summarizers by mode name."""
from __future__ import annotations

from .base import Summarizer
from .llm_based import LLMSummarizer
from .rule_based import RuleBasedSummarizer


def get_summarizer(mode: str = "rule", **kwargs) -> Summarizer:
    mode = (mode or "rule").lower()
    if mode == "rule":
        return RuleBasedSummarizer(**kwargs)
    if mode == "llm":
        return LLMSummarizer(**kwargs)
    raise ValueError(f"unknown summarizer mode: {mode!r}; use 'rule' or 'llm'")
