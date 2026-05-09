"""Render a Notion-friendly HTML post for one company."""
from __future__ import annotations

import html
from datetime import datetime
from typing import Iterable

from price.fetcher import PriceSnapshot
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


def _render_price_table(snap: PriceSnapshot) -> str:
    if snap.status != "ok":
        return (
            '<table border="1" cellspacing="0" cellpadding="6" '
            'style="border-collapse:collapse;width:100%;margin:8px 0">'
            '<thead><tr style="background:#fafafa">'
            "<th>Ticker</th><th>Status</th><th>Fetched at</th>"
            "</tr></thead><tbody>"
            f"<tr><td>{_esc(snap.ticker)}</td>"
            f'<td style="color:#d32f2f">{_esc(snap.status)}</td>'
            f"<td>{_esc(snap.fetched_at)}</td></tr>"
            "</tbody></table>"
        )

    head = (
        '<table border="1" cellspacing="0" cellpadding="6" '
        'style="border-collapse:collapse;width:100%;margin:8px 0">'
        '<thead><tr style="background:#fafafa">'
        "<th>Name</th><th>Ticker</th><th>Last close</th>"
        "<th>Change</th><th>Currency</th><th>Market cap</th><th>Fetched at</th>"
        "</tr></thead><tbody>"
    )
    body = (
        "<tr>"
        f"<td>{_esc(snap.name)}</td>"
        f"<td>{_esc(snap.ticker)}</td>"
        f'<td style="text-align:right">{_fmt_num(snap.last_close)}</td>'
        f'<td style="text-align:right">{_fmt_pct(snap.change_pct)}</td>'
        f"<td>{_esc(snap.currency)}</td>"
        f'<td style="text-align:right">{_fmt_num(snap.market_cap, 0)}</td>'
        f"<td>{_esc(snap.fetched_at)}</td>"
        "</tr>"
    )
    recent_block = ""
    if snap.last_5_closes:
        rows = "".join(
            f'<tr><td>{_esc(row["date"])}</td>'
            f'<td style="text-align:right">{_fmt_num(row["close"])}</td></tr>'
            for row in snap.last_5_closes
        )
        recent_block = (
            "<h3>Recent 5 closes</h3>"
            '<table border="1" cellspacing="0" cellpadding="6" '
            'style="border-collapse:collapse;margin:8px 0">'
            '<thead><tr style="background:#fafafa"><th>Date</th><th>Close</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )

    return head + body + "</tbody></table>" + recent_block


def _render_section(title: str, body: str) -> str:
    paragraphs = [p.strip() for p in (body or "").splitlines() if p.strip()]
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
    if source_items:
        items = "".join(f"<li>{_esc(source)}</li>" for source in source_items)
        source_block = f"<h3>Source files</h3><ul>{items}</ul>"

    target_block = ""
    if summary.target_price:
        target_block = (
            '<div style="padding:8px 12px;background:#f5f5f5;'
            'border-left:4px solid #1976d2;margin:12px 0">'
            f"<strong>Target price:</strong> {_esc(summary.target_price)}"
            "</div>"
        )

    return (
        f"<h1>{_esc(title)}</h1>"
        f'<p style="color:#666;font-size:13px">{" | ".join(meta_parts)}</p>'
        "<h2>Price snapshot</h2>"
        f"{_render_price_table(snap)}"
        f"{target_block}"
        f'{_render_section("Company overview", summary.overview)}'
        f'{_render_section("Investment thesis", summary.thesis)}'
        f'{_render_section("Risks", summary.risks)}'
        f'{_render_section("Conclusion / checkpoints", summary.conclusion)}'
        f"{source_block}"
    )
