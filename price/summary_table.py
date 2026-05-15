"""Build display rows for the price summary table."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .fetcher import PriceSnapshot


@dataclass(frozen=True)
class PriceSummaryRow:
    label: str
    date: str
    close: float | None
    change_pct: float | None
    market_cap: float | None


CURRENT_LABEL = "\ud604\uc7ac\uac00"
PREV_LABEL = "\uc804\uc77c \uc885\uac00"
TWO_DAYS_AGO_LABEL = "\uc774\ud2c0 \uc804 \uc885\uac00"
PRESENTATION_LABEL = "\ubc1c\ud45c\uc2dc\uc810 \uc885\uac00"
PRICE_SUMMARY_LABEL = "\uc8fc\uac00 \uc694\uc57d \ud45c"
PRICE_SUMMARY_HEADERS = ["\uad6c\ubd84", "\uae30\uc900\uc77c", "\uc885\uac00", "\ub4f1\ub77d\ub960", "\uc2dc\uac00\ucd1d\uc561"]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _close_row(row: dict[str, Any] | None) -> tuple[str, float | None]:
    if not row:
        return "-", None
    return str(row.get("date") or "-"), _float_or_none(row.get("close"))


def _ordered_closes(snap: PriceSnapshot) -> list[dict[str, Any]]:
    rows = snap.last_5_closes or snap.recent_closes or []
    return [row for row in rows if isinstance(row, dict)]


def _change_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / previous * 100, 2)


def _presentation_change(row: dict[str, Any] | None) -> float | None:
    if not row:
        return None
    return _float_or_none(row.get("change_pct"))


def build_price_summary_rows(snap: PriceSnapshot) -> list[PriceSummaryRow]:
    """Return the four rows used by HTML and Notion price toggles."""
    closes = _ordered_closes(snap)
    current_date, current_close = _close_row(closes[-1] if len(closes) >= 1 else None)
    prev_date, prev_close = _close_row(closes[-2] if len(closes) >= 2 else None)
    two_days_ago_date, two_days_ago_close = _close_row(closes[-3] if len(closes) >= 3 else None)

    if current_close is None:
        current_close = snap.last_close
    if prev_close is None:
        prev_close = snap.prev_close

    current_change = snap.change_pct
    if current_change is None:
        current_change = _change_pct(current_close, prev_close)

    prev_change = _change_pct(prev_close, two_days_ago_close)
    previous_for_two_days_ago = _float_or_none(closes[-4].get("close")) if len(closes) >= 4 else None
    two_days_ago_change = _change_pct(two_days_ago_close, previous_for_two_days_ago)

    presentation_date, presentation_close = _close_row(snap.presentation_close)
    return [
        PriceSummaryRow(CURRENT_LABEL, current_date, current_close, current_change, snap.market_cap),
        PriceSummaryRow(PREV_LABEL, prev_date, prev_close, prev_change, None),
        PriceSummaryRow(TWO_DAYS_AGO_LABEL, two_days_ago_date, two_days_ago_close, two_days_ago_change, None),
        PriceSummaryRow(
            PRESENTATION_LABEL,
            presentation_date,
            presentation_close,
            _presentation_change(snap.presentation_close),
            None,
        ),
    ]


def _format_number(value: float | None) -> str:
    if value is None:
        return "-"
    if abs(value - round(value)) < 0.005:
        return f"{value:,.0f}"
    return f"{value:,.2f}"


def format_close(value: float | None, currency: str | None = None) -> str:
    if value is None:
        return "-"
    currency = (currency or "").upper()
    if currency == "KRW":
        return f"{_format_number(value)}\uc6d0"
    if currency:
        return f"{_format_number(value)} {currency}"
    return _format_number(value)


def format_change_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def format_market_cap(value: float | None, currency: str | None = None) -> str:
    if value is None:
        return "-"
    currency = (currency or "").upper()
    if currency == "KRW":
        if abs(value) >= 1_000_000_000_000:
            return f"{value / 1_000_000_000_000:.2f}\uc870\uc6d0"
        if abs(value) >= 100_000_000:
            return f"{value / 100_000_000:,.0f}\uc5b5\uc6d0"
        return f"{_format_number(value)}\uc6d0"
    if abs(value) >= 1_000_000_000_000:
        text = f"{value / 1_000_000_000_000:.2f}T"
    elif abs(value) >= 1_000_000_000:
        text = f"{value / 1_000_000_000:.2f}B"
    elif abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    else:
        text = _format_number(value)
    return f"{text} {currency}".strip()
