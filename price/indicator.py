"""Target-price extraction and price-position indicator helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .fetcher import PriceSnapshot


TARGET_KEYWORDS = (
    "\ubaa9\ud45c\uc8fc\uac00",
    "\ubaa9\ud45c \uc8fc\uac00",
    "\ubaa9\ud45c\uac00",
    "target price",
    "price target",
)
BASE_KEYWORDS = ("base", "\uae30\uc900", "\ucee8\uc13c\uc11c\uc2a4")
AMOUNT_RE = re.compile(
    r"(?P<prefix>[$\uff04\u20a9]?)\s*"
    r"(?P<number>[0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(?P<suffix>\uc6d0|KRW|USD|\ub2ec\ub7ec|[$\uff04\u20a9])?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TargetPrice:
    display: str
    value: float
    source: str = ""
    is_base: bool = False


@dataclass(frozen=True)
class TargetPosition:
    target: TargetPrice | None
    current_price: float | None
    achievement_pct: float | None
    remaining_pct: float | None
    gauge: str
    status: str
    message: str

    @property
    def has_position(self) -> bool:
        return self.achievement_pct is not None


def _normalize_amount(match: re.Match[str]) -> tuple[str, float] | None:
    next_char = match.string[match.end() : match.end() + 1]
    if next_char in {"%", "\uff05"}:
        return None
    number_text = match.group("number")
    try:
        value = float(number_text.replace(",", ""))
    except ValueError:
        return None
    if value <= 0:
        return None

    prefix = (match.group("prefix") or "").strip()
    suffix = (match.group("suffix") or "").strip()
    display = f"{prefix}{number_text}{suffix}".strip()
    return display, value


def _has_target_keyword(text: str) -> bool:
    low = text.lower()
    return any(keyword.lower() in low for keyword in TARGET_KEYWORDS)


def _has_base_keyword(text: str) -> bool:
    low = text.lower()
    return any(keyword.lower() in low for keyword in BASE_KEYWORDS)


def _candidate_score(line: str, match: re.Match[str]) -> int:
    before = line[: match.start()]
    around = line[max(0, match.start() - 80) : match.end() + 80]
    score = 0
    if _has_base_keyword(around):
        score += 100
    if _has_target_keyword(before):
        score += 50
    elif _has_target_keyword(around):
        score += 20
    if match.group("prefix") or match.group("suffix"):
        score += 5
    return score


def extract_target_price(text: str) -> TargetPrice | None:
    """Extract the best available target price from presentation text.

    Base/consensus target prices are preferred over generic target prices.
    """
    candidates: list[tuple[int, int, TargetPrice]] = []
    for index, raw_line in enumerate((text or "").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if not (_has_target_keyword(line) or (_has_base_keyword(line) and "\ubaa9\ud45c" in line)):
            continue
        for match in AMOUNT_RE.finditer(line):
            normalized = _normalize_amount(match)
            if normalized is None:
                continue
            display, value = normalized
            score = _candidate_score(line, match)
            if score <= 0:
                continue
            context = line[max(0, match.start() - 80) : match.end() + 80]
            candidates.append(
                (
                    score,
                    -index,
                    TargetPrice(
                        display=display,
                        value=value,
                        source=line[:200],
                        is_base=_has_base_keyword(context),
                    ),
                )
            )

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def parse_target_price_value(text: str) -> TargetPrice | None:
    """Parse a target-price-like value from an already extracted summary field."""
    for match in AMOUNT_RE.finditer(text or ""):
        normalized = _normalize_amount(match)
        if normalized is None:
            continue
        display, value = normalized
        return TargetPrice(
            display=display,
            value=value,
            source=(text or "")[:200],
            is_base=_has_base_keyword(text or ""),
        )
    return None


def _gauge_for_achievement(achievement_pct: float) -> tuple[str, str]:
    if achievement_pct >= 100:
        return "[\U0001f525 OVER TARGET]", "\ubaa9\ud45c\uac00 \ub3cc\ud30c"
    if achievement_pct <= 60:
        return "[\u2593\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591\u2591]", "\uc800\ud3c9\uac00/\uc0c1\uc2b9\uc5ec\ub825 \ud07c"
    if achievement_pct <= 80:
        return "[\u2593\u2593\u2593\u2593\u2593\u2593\u2591\u2591\u2591\u2591]", "\uc911\uac04 \uc9c0\uc810"
    return "[\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2593\u2591]", "\ubaa9\ud45c\uac00 \uadfc\uc811"


def build_target_position(snap: PriceSnapshot, target: TargetPrice | None) -> TargetPosition:
    if target is None:
        return TargetPosition(
            target=None,
            current_price=snap.last_close,
            achievement_pct=None,
            remaining_pct=None,
            gauge="",
            status="\ubaa9\ud45c\uc8fc\uac00 \uc5c6\uc74c",
            message="\ubaa9\ud45c\uc8fc\uac00 \uc5c6\uc74c",
        )
    if target.value <= 0:
        return TargetPosition(
            target=target,
            current_price=snap.last_close,
            achievement_pct=None,
            remaining_pct=None,
            gauge="",
            status="\uacc4\uc0b0 \ubd88\uac00",
            message="\ubaa9\ud45c\uac00\uac00 0 \uc774\ud558\uc5ec\uc11c \uacc4\uc0b0 \ubd88\uac00",
        )
    if snap.last_close is None:
        return TargetPosition(
            target=target,
            current_price=None,
            achievement_pct=None,
            remaining_pct=None,
            gauge="",
            status="\uacc4\uc0b0 \ubd88\uac00",
            message="\ud604\uc7ac\uac00 \uc5c6\uc74c",
        )

    achievement = snap.last_close / target.value * 100
    remaining = max(0.0, 100 - achievement)
    gauge, status = _gauge_for_achievement(achievement)
    return TargetPosition(
        target=target,
        current_price=snap.last_close,
        achievement_pct=round(achievement, 1),
        remaining_pct=round(remaining, 1),
        gauge=gauge,
        status=status,
        message="",
    )


def format_target_position_line(position: TargetPosition) -> str:
    if not position.has_position:
        return f"\ubaa9\ud45c\uac00 \ub300\ube44 \uc704\uce58 | {position.message}"
    return (
        "\ubaa9\ud45c\uac00 \ub300\ube44 \uc704\uce58 | "
        f"{position.gauge} {position.achievement_pct:.1f}% | "
        f"\ubaa9\ud45c\uac00 \ub3c4\ub2ec\uae4c\uc9c0 {position.remaining_pct:.1f}%"
    )


def format_target_detail_line(position: TargetPosition) -> str:
    if position.target is None:
        return "\ubaa9\ud45c\uc8fc\uac00: \uc5c6\uc74c"
    current = "-" if position.current_price is None else f"{position.current_price:,.2f}"
    base = "Base " if position.target.is_base else ""
    return f"\ud604\uc7ac\uac00: {current} / {base}\ubaa9\ud45c\uac00: {position.target.display}"
