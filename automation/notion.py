"""Publish generated summaries to Notion."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

from price.fetcher import PriceSnapshot
from price.indicator import (
    build_target_position,
    format_target_detail_line,
    format_target_position_line,
    parse_target_price_value,
)
from summarizer.base import Summary


NOTION_VERSION = "2022-06-28"
PROP_COMPANY = "\uae30\uc5c5\uba85"
PROP_TICKER = "\ud2f0\ucee4"
PROP_MARKET = "\uc2dc\uc7a5"
PROP_PRESENTER = "\ubc1c\ud45c\uc790"
PROP_MONTH = "\ubc1c\ud45c\uc6d4"
PROP_SECTOR = "\uc0b0\uc5c5 \uc139\ud130"
PRICE_TREND_LABEL = "\uc2e4\uc2dc\uac04 \uc8fc\uac00 \ucd94\uc774"


@dataclass
class NotionTarget:
    token: str
    database_id: str = ""
    data_source_id: str = ""
    parent_page_id: str = ""
    title_property: str = PROP_COMPANY
    month_property: str = PROP_MONTH


class NotionClient:
    def __init__(self, token: str) -> None:
        self.token = token
        try:
            from notion_client import Client
        except ImportError as e:
            raise RuntimeError("notion-client is not installed; run pip install notion-client") from e
        self.client = Client(auth=token)
        self._data_source_cache: dict[str, str] = {}

    def request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method == "POST" and path == "/pages":
            return self.client.pages.create(**payload)
        if method == "POST" and path.startswith("/databases/") and path.endswith("/query"):
            database_id = path.removeprefix("/databases/").removesuffix("/query")
            if hasattr(self.client.databases, "query"):
                return self.client.databases.query(database_id=database_id, **payload)
            data_source_id = self._resolve_data_source_id(NotionTarget(token=self.token, database_id=database_id))
            return self.client.data_sources.query(data_source_id=data_source_id, **payload)
        raise RuntimeError(f"unsupported Notion request: {method} {path}")

    def _resolve_data_source_id(self, target: NotionTarget) -> str:
        if target.data_source_id:
            return target.data_source_id
        if not target.database_id:
            raise RuntimeError("Notion database_id or data_source_id is required")
        if target.database_id in self._data_source_cache:
            return self._data_source_cache[target.database_id]

        database = self.client.databases.retrieve(database_id=target.database_id)
        data_sources = database.get("data_sources") or []
        if not data_sources:
            raise RuntimeError(
                "Notion database has no data_sources. Set NOTION_DATA_SOURCE_ID "
                "to the data source ID copied from the Notion database menu."
            )
        data_source_id = str(data_sources[0].get("id") or "")
        if not data_source_id:
            raise RuntimeError("Notion database data_sources[0].id is empty")
        self._data_source_cache[target.database_id] = data_source_id
        return data_source_id

    def query_database(self, target: NotionTarget, payload: dict[str, Any]) -> dict[str, Any]:
        if not target.data_source_id and hasattr(self.client.databases, "query") and target.database_id:
            return self.client.databases.query(database_id=target.database_id, **payload)
        data_source_id = self._resolve_data_source_id(target)
        return self.client.data_sources.query(data_source_id=data_source_id, **payload)

    def find_existing_page(self, target: NotionTarget, company: str, presentation_month: str) -> str | None:
        payload = duplicate_query_payload(target.title_property, target.month_property, company, presentation_month)
        result = self.query_database(target, payload)
        results = result.get("results") or []
        if not results:
            return None
        return str(results[0].get("id") or "")

    def create_page(
        self,
        target: NotionTarget,
        title: str,
        children: list[dict[str, Any]],
        extra_properties: dict[str, Any] | None = None,
    ) -> str:
        use_data_source_parent = bool(target.data_source_id) or not hasattr(self.client.databases, "query")
        if use_data_source_parent and (target.data_source_id or target.database_id):
            parent = {"data_source_id": self._resolve_data_source_id(target)}
            properties = {
                target.title_property: {
                    "title": [{"text": {"content": title[:2000]}}],
                }
            }
        elif target.database_id:
            parent = {"database_id": target.database_id}
            properties = {
                target.title_property: {
                    "title": [{"text": {"content": title[:2000]}}],
                }
            }
        elif target.parent_page_id:
            parent = {"page_id": target.parent_page_id}
            properties = {
                "title": {
                    "title": [{"text": {"content": title[:2000]}}],
                }
            }
        else:
            raise RuntimeError("Notion target needs database_id or parent_page_id")

        if extra_properties:
            properties.update(extra_properties)

        page = self.client.pages.create(parent=parent, properties=properties, children=children[:100])
        return page["id"]

    def list_child_blocks(self, block_id: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            result = self.client.blocks.children.list(**payload)
            blocks.extend(result.get("results") or [])
            if not result.get("has_more"):
                break
            cursor = result.get("next_cursor")
            if not cursor:
                break
        return blocks

    def archive_block(self, block_id: str) -> None:
        self.client.blocks.update(block_id=block_id, archived=True)

    def append_blocks(self, block_id: str, children: list[dict[str, Any]]) -> None:
        self.client.blocks.children.append(block_id=block_id, children=children[:100])

    def replace_price_trend_toggle(self, page_id: str, toggle_block: dict[str, Any]) -> None:
        for block in self.list_child_blocks(page_id):
            if block.get("type") != "toggle":
                continue
            if _plain_text(block.get("toggle", {}).get("rich_text", [])) == PRICE_TREND_LABEL:
                block_id = str(block.get("id") or "")
                if block_id:
                    self.archive_block(block_id)
        self.append_blocks(page_id, [toggle_block])


def target_from_config(config: dict[str, Any]) -> NotionTarget | None:
    notion = (config.get("automation", {}) or {}).get("notion", {}) or config.get("notion", {}) or {}
    has_env_target = os.environ.get("NOTION_DATABASE_ID") or os.environ.get("NOTION_DATA_SOURCE_ID")
    if not notion and not (os.environ.get("NOTION_TOKEN") and has_env_target):
        return None

    token_env = notion.get("token_env", "NOTION_TOKEN")
    token = notion.get("token") or os.environ.get(token_env, "")
    if not token:
        raise RuntimeError(f"Notion token is missing; set {token_env}")

    return NotionTarget(
        token=token,
        database_id=os.environ.get("NOTION_DATABASE_ID") or notion.get("database_id", ""),
        data_source_id=os.environ.get("NOTION_DATA_SOURCE_ID") or notion.get("data_source_id", ""),
        parent_page_id=notion.get("parent_page_id", ""),
        title_property=notion.get("title_property", PROP_COMPANY),
        month_property=notion.get("month_property", PROP_MONTH),
    )


def _rich_text(text: str) -> list[dict[str, Any]]:
    text = text or ""
    if not text:
        return [{"text": {"content": ""}}]
    return [{"text": {"content": text[:2000]}}]


def _plain_text(rich_text: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in rich_text or []:
        parts.append(str(item.get("plain_text") or item.get("text", {}).get("content") or ""))
    return "".join(parts)


def _paragraph(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _toggle(text: str, children: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {"rich_text": _rich_text(text), "children": children},
    }


def _bulleted_item(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rich_text(text)}}


def _numbered_item(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "numbered_list_item", "numbered_list_item": {"rich_text": _rich_text(text)}}


def _heading(level: int, text: str) -> dict[str, Any]:
    block_type = f"heading_{level}"
    return {"object": "block", "type": block_type, block_type: {"rich_text": _rich_text(text)}}


def _split_paragraphs(text: str) -> Iterable[str]:
    parts = [p.strip() for p in (text or "").splitlines() if p.strip()]
    return parts or ["(empty)"]


def _blocks_from_markdown_lines(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line in _split_paragraphs(text):
        heading = line.lstrip()
        if heading.startswith("### "):
            blocks.append(_heading(3, heading[4:].strip()))
        elif heading.startswith("## "):
            blocks.append(_heading(2, heading[3:].strip()))
        elif heading.startswith("# "):
            blocks.append(_heading(1, heading[2:].strip()))
        elif line[:2] in {"- ", "* "}:
            blocks.append(_bulleted_item(line[2:].strip()))
        else:
            numbered = re.match(r"^\d+[\.)]\s+(.+)$", line)
            if numbered:
                blocks.append(_numbered_item(numbered.group(1).strip()))
            else:
                blocks.append(_paragraph(line))
    return blocks


_SOURCE_RE = re.compile(r"\[(?:\ucd9c\ucc98|source)\s*:", re.IGNORECASE)


def _strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s+|\d+[\.)]\s+)", "", line).strip()


def _fallback_source(sources: list[str]) -> str:
    for source in sources:
        if source:
            return source
    return ""


def _with_source_marker(line: str, fallback_source: str = "") -> str:
    line = _strip_bullet_prefix(line)
    if not line or _SOURCE_RE.search(line):
        return line
    if fallback_source:
        return f"{line} [\ucd9c\ucc98: {fallback_source}]"
    return line


def _summary_lines(text: str, fallback_source: str = "") -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = _with_source_marker(raw, fallback_source)
        if line:
            lines.append(line)
    return lines


def _blocks_from_cited_lines(text: str, fallback_source: str = "") -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line in _summary_lines(text, fallback_source):
        if line[:2] in {"- ", "* "}:
            blocks.append(_bulleted_item(line[2:].strip()))
        else:
            blocks.append(_paragraph(line))
    return blocks or [_paragraph("(empty)")]


def _table_row(cells: list[str]) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "table_row",
        "table_row": {"cells": [_rich_text(cell) for cell in cells]},
    }


def _investment_table(summary: Summary, fallback_source: str) -> dict[str, Any]:
    thesis = _summary_lines(summary.thesis, fallback_source)
    risks = _summary_lines(summary.risks, fallback_source)
    thesis_cell = "\n".join(f"- {line}" for line in thesis) or "(empty)"
    risks_cell = "\n".join(f"- {line}" for line in risks) or "(empty)"
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": 2,
            "has_column_header": True,
            "has_row_header": False,
            "children": [
                _table_row(
                    [
                        "\ud22c\uc790 \uc544\uc774\ub514\uc5b4(Upside)",
                        "\ud22c\uc790 \ub9ac\uc2a4\ud06c(Downside)",
                    ]
                ),
                _table_row([thesis_cell, risks_cell]),
            ],
        },
    }


def _rich_text_property(text: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": text[:2000]}}]} if text else {"rich_text": []}


def _select_property(value: str) -> dict[str, Any]:
    return {"select": {"name": value}} if value else {"select": None}


def _multi_select_property(values: list[str]) -> dict[str, Any]:
    return {"multi_select": [{"name": value} for value in values]}


def _market_from_ticker(ticker: str) -> str:
    ticker = (ticker or "").upper()
    if ticker.endswith(".KS"):
        return "KOSPI"
    if ticker.endswith(".KQ"):
        return "KOSDAQ"
    return ""


def properties_for_post(summary: Summary, sectors: list[str] | None = None) -> dict[str, Any]:
    """Build optional Notion database properties for generated posts."""
    sectors = sectors or []
    properties: dict[str, Any] = {}
    if summary.ticker:
        properties[PROP_TICKER] = _rich_text_property(summary.ticker)
        market = _market_from_ticker(summary.ticker)
        if market:
            properties[PROP_MARKET] = _select_property(market)
    if summary.presenter:
        properties[PROP_PRESENTER] = _select_property(summary.presenter)
    if summary.presentation_month:
        properties[PROP_MONTH] = _rich_text_property(summary.presentation_month)
    if sectors:
        properties[PROP_SECTOR] = _multi_select_property(sectors)
    return properties


def duplicate_query_payload(
    title_property: str,
    month_property: str,
    company: str,
    presentation_month: str,
) -> dict[str, Any]:
    return {
        "filter": {
            "and": [
                {"property": title_property, "title": {"equals": company}},
                {"property": month_property, "rich_text": {"equals": presentation_month}},
            ]
        },
        "page_size": 1,
    }


def _fmt_money(value: float | None, currency: str | None = None) -> str:
    if value is None:
        return "-"
    unit = currency or ""
    if abs(value) >= 1_000_000_000_000:
        text = f"{value / 1_000_000_000_000:.2f}T"
    elif abs(value) >= 1_000_000_000:
        text = f"{value / 1_000_000_000:.2f}B"
    elif abs(value) >= 1_000_000:
        text = f"{value / 1_000_000:.2f}M"
    else:
        text = f"{value:,.2f}"
    return f"{text} {unit}".strip()


def price_trend_toggle_block(snap: PriceSnapshot, target_price_text: str = "") -> dict[str, Any]:
    position = build_target_position(snap, parse_target_price_value(target_price_text))
    children: list[dict[str, Any]] = [
        _paragraph(format_target_position_line(position)),
        _paragraph(format_target_detail_line(position)),
    ]
    if snap.last_5_closes:
        children.extend(
            _bulleted_item(f"{row.get('date', '-')}: {row.get('close', '-')}")
            for row in snap.last_5_closes
        )
    else:
        ticker = snap.ticker or "-"
        children.append(_paragraph(f"{ticker}: {snap.status} ({snap.fetched_at})"))
    return _toggle(PRICE_TREND_LABEL, children)


def blocks_for_post(summary: Summary, snap: PriceSnapshot, sources: list[str]) -> list[dict[str, Any]]:
    title = summary.company or "Untitled"
    if summary.ticker:
        title += f" ({summary.ticker})"

    fallback_source = _fallback_source(sources)

    blocks: list[dict[str, Any]] = [
        _heading(1, title),
        _paragraph(f"Presenter: {summary.presenter or '-'}"),
        _paragraph(f"Presentation month: {summary.presentation_month or '-'}"),
        price_trend_toggle_block(snap, summary.target_price),
    ]

    blocks.append(_heading(2, "\uae30\uc5c5 \uac1c\uc694"))
    blocks.extend(_blocks_from_cited_lines(summary.overview, fallback_source))
    blocks.append(_heading(2, "\ud22c\uc790 \uc544\uc774\ub514\uc5b4 & \ud22c\uc790 \ub9ac\uc2a4\ud06c"))
    blocks.append(_investment_table(summary, fallback_source))

    if sources:
        blocks.append(_heading(3, "Source files"))
        blocks.extend(_bulleted_item(source) for source in sources)

    return blocks
