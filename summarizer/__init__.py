"""발표자료 요약 모듈 - 규칙 기반과 LLM 기반 모두 지원."""
from .base import Summary, Summarizer
from .rule_based import RuleBasedSummarizer
from .llm_based import LLMSummarizer
from .factory import get_summarizer
from .sector_classifier import (
    SECTOR_TAXONOMY,
    VALID_SECTORS,
    SectorClassifier,
    build_sector_prompt,
    parse_sector_response,
)

__all__ = [
    "Summary",
    "Summarizer",
    "RuleBasedSummarizer",
    "LLMSummarizer",
    "get_summarizer",
    "SECTOR_TAXONOMY",
    "VALID_SECTORS",
    "SectorClassifier",
    "build_sector_prompt",
    "parse_sector_response",
]
