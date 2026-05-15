"""Render a Notion-friendly HTML post for one company."""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Iterable

from price.fetcher import PriceSnapshot
from price.indicator import (
    build_target_position,
    format_target_detail_line,
    format_target_position_line,
    parse_target_price_value,
)
from price.summary_table import (
    PRICE_SUMMARY_HEADERS,
    PRICE_SUMMARY_LABEL,
    build_price_summary_rows,
    format_change_pct,
    format_close,
    format_market_cap,
)
from summarizer.base import Summary
from summarizer.overview import normalize_overview_lines


def _esc(value: str | None) -> str:
    return html.escape(str(value or ""), quote=True)


_SOURCE_RE = re.compile(r"\[(?:\ucd9c\ucc98|source)\s*:", re.IGNORECASE)


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|\d+[\.)]\s+)", "", line).strip()


def _fallback_source(sources: Iterable[str]) -> str:
    for source in sources:
        if source:
            return str(source)
    return ""


def _with_source_marker(line: str, fallback_source: str = "") -> str:
    line = _strip_bullet_prefix(line)
    if not line or _SOURCE_RE.search(line):
        return line
    return line


def _summary_lines(body: str, fallback_source: str = "") -> list[str]:
    lines = []
    for raw in (body or "").splitlines():
        line = _with_source_marker(raw, fallback_source)
        if line:
            lines.append(line)
    return lines


def _render_change_pct(value: float | None) -> str:
    if value is None:
        return "-"
    color = "#d32f2f" if value > 0 else ("#1976d2" if value < 0 else "#666")
    return f'<span style="color:{color};font-weight:600">{_esc(format_change_pct(value))}</span>'


def _render_price_summary_table(snap: PriceSnapshot) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{_esc(row.label)}</td>"
        f'<td style="text-align:right">{_esc(row.date)}</td>'
        f'<td style="text-align:right">{_esc(format_close(row.close, snap.currency))}</td>'
        f'<td style="text-align:right">{_render_change_pct(row.change_pct)}</td>'
        f'<td style="text-align:right">{_esc(format_market_cap(row.market_cap, snap.currency))}</td>'
        "</tr>"
        for row in build_price_summary_rows(snap)
    )
    header = "".join(f"<th>{_esc(text)}</th>" for text in PRICE_SUMMARY_HEADERS)
    return (
        f"<h3>{_esc(PRICE_SUMMARY_LABEL)}</h3>"
        '<table border="1" cellspacing="0" cellpadding="6" '
        'style="border-collapse:collapse;margin:8px 0;width:100%">'
        f'<thead><tr style="background:#fafafa">{header}</tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def _render_price_trend_toggle(snap: PriceSnapshot, target_price_text: str = "") -> str:
    position = build_target_position(snap, parse_target_price_value(target_price_text))
    indicator = (
        "<p>"
        f"<strong>{_esc(format_target_position_line(position))}</strong><br>"
        f"{_esc(format_target_detail_line(position))}"
        "</p>"
    )
    body = indicator + _render_price_summary_table(snap)

    return (
        "<details>"
        "<summary>\uc2e4\uc2dc\uac04 \uc8fc\uac00 \ucd94\uc774</summary>"
        f"{body}"
        "</details>"
    )


def _render_bullet_list(lines: list[str]) -> str:
    if not lines:
        return '<p style="color:#999">(empty)</p>'
    return "<ul>" + "".join(f"<li>{_esc(line)}</li>" for line in lines) + "</ul>"


def _render_investment_table(summary: Summary, fallback_source: str) -> str:
    thesis = _summary_lines(summary.thesis, "")
    risks = _summary_lines(summary.risks, "")
    return (
        "<h2>\ud22c\uc790 \uc544\uc774\ub514\uc5b4 & \ud22c\uc790 \ub9ac\uc2a4\ud06c</h2>"
        '<table border="1" cellspacing="0" cellpadding="8" '
        'style="border-collapse:collapse;width:100%;margin:8px 0;vertical-align:top">'
        '<thead><tr style="background:#fafafa">'
        "<th>\ud22c\uc790 \uc544\uc774\ub514\uc5b4(Upside)</th>"
        "<th>\ud22c\uc790 \ub9ac\uc2a4\ud06c(Downside)</th>"
        "</tr></thead><tbody><tr>"
        f'<td style="vertical-align:top;width:50%">{_render_bullet_list(thesis)}</td>'
        f'<td style="vertical-align:top;width:50%">{_render_bullet_list(risks)}</td>'
        "</tr></tbody></table>"
    )


def _render_section(title: str, body: str) -> str:
    paragraphs = [p.strip() for p in (body or "").splitlines() if p.strip()]
    if not paragraphs:
        return f'<h2>{_esc(title)}</h2><p style="color:#999">(empty)</p>'
    return f"<h2>{_esc(title)}</h2>" + "".join(f"<p>{_esc(p)}</p>" for p in paragraphs)


def _render_cited_section(title: str, body: str, fallback_source: str) -> str:
    paragraphs = _summary_lines(body, fallback_source)
    if not paragraphs:
        return f'<h2>{_esc(title)}</h2><p style="color:#999">(empty)</p>'
    return f"<h2>{_esc(title)}</h2>" + "".join(f"<p>{_esc(p)}</p>" for p in paragraphs)


def _render_overview_section(body: str, fallback_source: str) -> str:
    paragraphs = normalize_overview_lines(body, "")
    return "<h2>Company overview</h2>" + "".join(f"<p>{_esc(p)}</p>" for p in paragraphs)


def render_post(summary: Summary, snap: PriceSnapshot, sources: Iterable[str] = ()) -> str:
    title = summary.company or "(unknown company)"
    if summary.ticker or snap.ticker:
        title += f" ({summary.ticker or snap.ticker})"

    meta_parts = []
    if summary.presenter:
        meta_parts.append(f"Presenter: {_esc(summary.presenter)}")
    meta_parts.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    source_block = ""
    source_items = list(sources)
    if source_items:
        items = "".join(f"<li>{_esc(source)}</li>" for source in source_items)
        source_block = f"<h3>Source files</h3><ul>{items}</ul>"

    return (
        f"<h1>{_esc(title)}</h1>"
        f'<p style="color:#666;font-size:13px">{" | ".join(meta_parts)}</p>'
        f"{_render_price_trend_toggle(snap, summary.target_price)}"
        f"{_render_overview_section(summary.overview, '')}"
        f"{_render_investment_table(summary, '')}"
        f"{source_block}"
    )
