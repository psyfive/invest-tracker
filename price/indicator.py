"""Target-price extraction and price-position indicator helpers."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .fetcher import PriceSnapshot


TARGET_KEYWORDS = (
    "목표주가",
    "목표 주가",
    "목표가",
    "target price",
    "price target",
)
BASE_KEYWORDS = ("base", "기준", "컨센서스")
SCENARIO_LABELS = ("bear", "base", "bull")
INVALID_SUFFIX_RE = re.compile(r"^\s*(년|월|일|E\b|EPS\b|PER\b|배|[%％])", re.IGNORECASE)
INVALID_PREFIX_RE = re.compile(r"(EPS|PER)\s*$", re.IGNORECASE)
AMOUNT_RE = re.compile(
    r"(?P<prefix>[$＄₩]?)\s*"
    r"(?P<number>[0-9][0-9,]*(?:\.[0-9]+)?)\s*"
    r"(?P<suffix>원|KRW|USD|달러|[$＄₩])?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RejectedTargetCandidate:
    display: str
    reason: str
    source: str


@dataclass(frozen=True)
class TargetPriceScenario:
    label: str
    display: str
    value: float
    source: str = ""


@dataclass(frozen=True)
class TargetPrice:
    display: str
    value: float
    source: str = ""
    is_base: bool = False
    scenarios: tuple[TargetPriceScenario, ...] = ()
    representative_label: str = ""
    rejected_candidates: tuple[RejectedTargetCandidate, ...] = ()


@dataclass(frozen=True)
class TargetPosition:
    target: TargetPrice | None
    current_price: float | None
    achievement_pct: float | None
    remaining_pct: float | None
    gauge: str
    status: str
    message: str
    warnings: tuple[str, ...] = ()

    @property
    def has_position(self) -> bool:
        return self.achievement_pct is not None


@dataclass(frozen=True)
class _Candidate:
    display: str
    value: float
    source: str
    index: int
    score: int
    has_currency: bool
    is_base: bool
    scenario: str = ""


def _normalize_amount(match: re.Match[str]) -> tuple[str, float] | None:
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


def _currency_marker(match: re.Match[str]) -> bool:
    return bool((match.group("prefix") or "").strip() or (match.group("suffix") or "").strip())


def _scenario_label_near(line: str, match: re.Match[str]) -> str:
    low = line.lower()
    best_label = ""
    best_distance: int | None = None
    for label in SCENARIO_LABELS:
        for found in re.finditer(rf"\b{label}\b", low):
            distance = min(abs(match.start() - found.start()), abs(match.start() - found.end()))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_label = label
    return best_label if best_distance is not None and best_distance <= 24 else ""


def _target_keyword_distance(line: str, match: re.Match[str]) -> int | None:
    low = line.lower()
    start = match.start()
    distances: list[int] = []
    for keyword in TARGET_KEYWORDS:
        keyword_low = keyword.lower()
        pos = low.find(keyword_low)
        while pos >= 0:
            distances.append(min(abs(start - pos), abs(start - (pos + len(keyword_low)))))
            pos = low.find(keyword_low, pos + 1)
    return min(distances) if distances else None


def _has_strong_target_context(line: str, match: re.Match[str]) -> bool:
    distance = _target_keyword_distance(line, match)
    if distance is None or distance > 18:
        return False
    before = line[max(0, match.start() - 24) : match.start()]
    return bool(re.search(r"(목표\s*주가|목표가|target price|price target)\s*[:(]?\s*$", before, re.IGNORECASE))


def _candidate_rejection_reason(line: str, match: re.Match[str], *, allow_unitless: bool) -> str:
    prev_char = line[match.start() - 1 : match.start()]
    before = line[: match.start()]
    next_text = line[match.end() :]
    next_char = next_text[:1]
    if prev_char and (prev_char.isalpha() or prev_char.isdigit()) and not _has_strong_target_context(line, match):
        return "attached_to_identifier"
    if next_char and next_char.isalpha():
        return "attached_to_identifier"
    if INVALID_PREFIX_RE.search(before):
        return "financial_metric_prefix"
    if INVALID_SUFFIX_RE.match(next_text):
        return "non_price_suffix"
    if not _currency_marker(match):
        if not allow_unitless:
            return "missing_currency"
        if not _has_strong_target_context(line, match):
            return "weak_unitless_context"
    return ""


def _candidate_score(line: str, match: re.Match[str]) -> int:
    around = line[max(0, match.start() - 80) : match.end() + 80]
    score = 0
    if _currency_marker(match):
        score += 200

    distance = _target_keyword_distance(line, match)
    if distance is not None:
        if distance <= 8:
            score += 120
        elif distance <= 18:
            score += 80
        else:
            score += 30

    scenario = _scenario_label_near(line, match)
    if scenario == "base":
        score += 60
    elif scenario in {"bear", "bull"}:
        score += 20
    elif _has_base_keyword(around):
        score += 40
    return score


def _collect_candidates(
    text: str,
    *,
    require_target_line: bool,
    allow_unitless: bool,
) -> tuple[list[_Candidate], list[RejectedTargetCandidate]]:
    candidates: list[_Candidate] = []
    rejected: list[RejectedTargetCandidate] = []
    for index, raw_line in enumerate((text or "").splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        if require_target_line and not (_has_target_keyword(line) or (_has_base_keyword(line) and "목표" in line)):
            continue
        for match in AMOUNT_RE.finditer(line):
            normalized = _normalize_amount(match)
            if normalized is None:
                continue
            display, value = normalized
            reason = _candidate_rejection_reason(line, match, allow_unitless=allow_unitless)
            if reason:
                rejected.append(RejectedTargetCandidate(display=display, reason=reason, source=line[:200]))
                continue
            score = _candidate_score(line, match)
            if score <= 0:
                rejected.append(RejectedTargetCandidate(display=display, reason="no_target_context", source=line[:200]))
                continue
            context = line[max(0, match.start() - 80) : match.end() + 80]
            candidates.append(
                _Candidate(
                    display=display,
                    value=value,
                    source=line[:200],
                    index=index,
                    score=score,
                    has_currency=_currency_marker(match),
                    is_base=_has_base_keyword(context),
                    scenario=_scenario_label_near(line, match),
                )
            )
    return candidates, rejected


def _best_candidate(candidates: list[_Candidate]) -> _Candidate | None:
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda item: (
            item.score,
            int(item.has_currency),
            int(item.scenario == "base"),
            -item.index,
        ),
        reverse=True,
    )
    return ranked[0]


def _format_representative_display(value: float, reference_display: str) -> str:
    if "원" in reference_display or "KRW" in reference_display.upper():
        return f"{value:,.0f}원"
    if reference_display.startswith(("$", "＄")):
        return f"${value:,.2f}".rstrip("0").rstrip(".")
    if reference_display.upper().endswith("USD"):
        return f"{value:,.2f}".rstrip("0").rstrip(".") + "USD"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _build_target_price(
    candidates: list[_Candidate],
    rejected: list[RejectedTargetCandidate],
) -> TargetPrice | None:
    best = _best_candidate(candidates)
    if best is None:
        return None

    scenario_map: dict[str, _Candidate] = {}
    for label in SCENARIO_LABELS:
        scenario_candidates = [candidate for candidate in candidates if candidate.scenario == label]
        scenario_best = _best_candidate(scenario_candidates)
        if scenario_best is not None:
            scenario_map[label] = scenario_best

    scenarios = tuple(
        TargetPriceScenario(
            label=label,
            display=scenario_map[label].display,
            value=scenario_map[label].value,
            source=scenario_map[label].source,
        )
        for label in SCENARIO_LABELS
        if label in scenario_map
    )

    if all(label in scenario_map for label in SCENARIO_LABELS):
        representative_value = (
            scenario_map["bear"].value * 0.25
            + scenario_map["base"].value * 0.50
            + scenario_map["bull"].value * 0.25
        )
        return TargetPrice(
            display=_format_representative_display(representative_value, scenario_map["base"].display),
            value=representative_value,
            source=scenario_map["base"].source,
            is_base=True,
            scenarios=scenarios,
            representative_label="weighted_average",
            rejected_candidates=tuple(rejected),
        )

    if "base" in scenario_map:
        base = scenario_map["base"]
        return TargetPrice(
            display=base.display,
            value=base.value,
            source=base.source,
            is_base=True,
            scenarios=scenarios,
            representative_label="base",
            rejected_candidates=tuple(rejected),
        )

    return TargetPrice(
        display=best.display,
        value=best.value,
        source=best.source,
        is_base=best.is_base,
        scenarios=scenarios,
        representative_label="base" if best.is_base else "",
        rejected_candidates=tuple(rejected),
    )


def extract_target_price(text: str) -> TargetPrice | None:
    """Extract the best available target price from presentation text."""
    candidates, rejected = _collect_candidates(text, require_target_line=True, allow_unitless=True)
    return _build_target_price(candidates, rejected)


def parse_target_price_value(text: str) -> TargetPrice | None:
    """Parse a target-price-like value from an already extracted summary field."""
    candidates, rejected = _collect_candidates(text, require_target_line=False, allow_unitless=True)
    return _build_target_price(candidates, rejected)


def format_target_price_source_text(target: TargetPrice | None) -> str:
    if target is None:
        return ""
    if target.scenarios:
        return "\n".join(
            f"{scenario.label.title()} 목표가: {scenario.display}"
            for scenario in target.scenarios
        )
    return target.display


def _gauge_for_achievement(achievement_pct: float) -> tuple[str, str]:
    if achievement_pct >= 100:
        return "[🔥 OVER TARGET]", "목표가 돌파"
    if achievement_pct <= 60:
        return "[▓░░░░░░░░░]", "저평가/상승여력 큼"
    if achievement_pct <= 80:
        return "[▓▓▓▓▓▓░░░░]", "중간 지점"
    return "[▓▓▓▓▓▓▓▓▓░]", "목표가 근접"


def _target_warnings(snap: PriceSnapshot, target: TargetPrice) -> tuple[str, ...]:
    if snap.last_close is None or snap.last_close <= 0 or target.value <= 0:
        return ()
    ratio = target.value / snap.last_close
    if ratio < 0.1 or ratio > 10:
        return ("suspicious_target_price",)
    return ()


def build_target_position(snap: PriceSnapshot, target: TargetPrice | None) -> TargetPosition:
    if target is None:
        return TargetPosition(
            target=None,
            current_price=snap.last_close,
            achievement_pct=None,
            remaining_pct=None,
            gauge="",
            status="목표주가 없음",
            message="목표주가 없음",
        )
    warnings = _target_warnings(snap, target)
    if target.value <= 0:
        return TargetPosition(
            target=target,
            current_price=snap.last_close,
            achievement_pct=None,
            remaining_pct=None,
            gauge="",
            status="계산 불가",
            message="목표가가 0 이하여서 계산 불가",
            warnings=warnings,
        )
    if snap.last_close is None:
        return TargetPosition(
            target=target,
            current_price=None,
            achievement_pct=None,
            remaining_pct=None,
            gauge="",
            status="계산 불가",
            message="현재가 없음",
            warnings=warnings,
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
        warnings=warnings,
    )


def format_target_position_line(position: TargetPosition) -> str:
    if not position.has_position:
        return f"목표가 대비 위치 | {position.message}"
    return (
        "목표가 대비 위치 | "
        f"{position.gauge} {position.achievement_pct:.1f}% | "
        f"목표가 도달까지 {position.remaining_pct:.1f}%"
    )


def format_target_detail_line(position: TargetPosition) -> str:
    if position.target is None:
        return "목표주가: 없음"
    current = "-" if position.current_price is None else f"{position.current_price:,.2f}"
    if position.target.scenarios:
        scenario_text = " / ".join(
            f"{scenario.label.title()}: {scenario.display}"
            for scenario in position.target.scenarios
        )
        if position.target.representative_label == "weighted_average":
            return f"현재가: {current} / {scenario_text} / 가중평균 목표가: {position.target.display}"
        return f"현재가: {current} / {scenario_text} / 대표 목표가: {position.target.display}"
    base = "Base " if position.target.is_base else ""
    return f"현재가: {current} / {base}목표가: {position.target.display}"
