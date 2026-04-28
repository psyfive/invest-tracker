"""Summary result models and summarizer interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass


@dataclass
class Summary:
    """A normalized summary for one company presentation."""

    company: str
    ticker: str = ""
    presenter: str = ""
    overview: str = ""
    thesis: str = ""
    risks: str = ""
    target_price: str = ""
    raw_excerpt: str = ""

    def as_dict(self) -> dict:
        return asdict(self)

    def is_empty(self) -> bool:
        return not (self.overview or self.thesis or self.risks or self.target_price)


class Summarizer(ABC):
    """Convert extracted presentation text into a Summary."""

    @abstractmethod
    def summarize(
        self,
        text: str,
        company: str,
        ticker: str = "",
        presenter: str = "",
    ) -> Summary:
        ...
