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
from summarizer.base import Summary


def _esc(value: str | None) -> str:
    return html.escape(str(value or ""), quote=True)


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1000:
        return f"{value:,.{digits}f}"
    return f"{value:.{digits}f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    color = "#d32f2f" if value > 0 else ("#1976d2" if value < 0 else "#666")
    return f'<span style="color:{color};font-weight:600">{sign}{value:.2f}%</span>'


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
    if fallback_source:
        return f"{line} [\ucd9c\ucc98: {fallback_source}]"
    return line


def _summary_lines(body: str, fallback_source: str = "") -> list[str]:
    lines = []
    for raw in (body or "").splitlines():
        line = _with_source_marker(raw, fallback_source)
        if line:
            lines.append(line)
    return lines


def _render_price_trend_toggle(snap: PriceSnapshot, target_price_text: str = "") -> str:
    position = build_target_position(snap, parse_target_price_value(target_price_text))
    indicator = (
        "<p>"
        f"<strong>{_esc(format_target_position_line(position))}</strong><br>"
        f"{_esc(format_target_detail_line(position))}"
        "</p>"
    )
    if snap.last_5_closes:
        rows = "".join(
            f'<tr><td>{_esc(row["date"])}</td>'
            f'<td style="text-align:right">{_fmt_num(row["close"])}</td></tr>'
            for row in snap.last_5_closes
        )
        body = indicator + (
            '<table border="1" cellspacing="0" cellpadding="6" '
            'style="border-collapse:collapse;margin:8px 0">'
            '<thead><tr style="background:#fafafa"><th>\ub0a0\uc9dc</th><th>\uc885\uac00</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
    else:
        ticker = snap.ticker or "-"
        body = indicator + (
            f"<p>{_esc(ticker)}: {_esc(snap.status)}"
            f" ({_esc(snap.fetched_at)})</p>"
        )

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
    thesis = _summary_lines(summary.thesis, fallback_source)
    risks = _summary_lines(summary.risks, fallback_source)
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
    fallback_source = _fallback_source(source_items)
    if source_items:
        items = "".join(f"<li>{_esc(source)}</li>" for source in source_items)
        source_block = f"<h3>Source files</h3><ul>{items}</ul>"

    return (
        f"<h1>{_esc(title)}</h1>"
        f'<p style="color:#666;font-size:13px">{" | ".join(meta_parts)}</p>'
        f"{_render_price_trend_toggle(snap, summary.target_price)}"
        f'{_render_cited_section("Company overview", summary.overview, fallback_source)}'
        f"{_render_investment_table(summary, fallback_source)}"
        f"{source_block}"
    )
