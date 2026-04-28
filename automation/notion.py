"""Publish generated summaries to Notion."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

from price.fetcher import PriceSnapshot
from summarizer.base import Summary


NOTION_VERSION = "2022-06-28"


@dataclass
class NotionTarget:
    token: str
    database_id: str = ""
    parent_page_id: str = ""
    title_property: str = "Name"


class NotionClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def request(self, method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.notion.com/v1{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Notion-Version": NOTION_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Notion API failed ({e.code}): {body}") from e

    def create_page(
        self,
        target: NotionTarget,
        title: str,
        children: list[dict[str, Any]],
        extra_properties: dict[str, Any] | None = None,
    ) -> str:
        if target.database_id:
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

        page = self.request(
            "POST",
            "/pages",
            {"parent": parent, "properties": properties, "children": children[:100]},
        )
        return page["id"]


def target_from_config(config: dict[str, Any]) -> NotionTarget | None:
    notion = (config.get("automation", {}) or {}).get("notion", {}) or config.get("notion", {}) or {}
    if not notion:
        return None

    token_env = notion.get("token_env", "NOTION_TOKEN")
    token = notion.get("token") or os.environ.get(token_env, "")
    if not token:
        raise RuntimeError(f"Notion token is missing; set {token_env}")

    return NotionTarget(
        token=token,
        database_id=notion.get("database_id", ""),
        parent_page_id=notion.get("parent_page_id", ""),
        title_property=notion.get("title_property", "Name"),
    )


def _rich_text(text: str) -> list[dict[str, Any]]:
    text = text or ""
    if not text:
        return [{"text": {"content": ""}}]
    return [{"text": {"content": text[:2000]}}]


def _paragraph(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text(text)}}


def _heading(level: int, text: str) -> dict[str, Any]:
    block_type = f"heading_{level}"
    return {"object": "block", "type": block_type, block_type: {"rich_text": _rich_text(text)}}


def _split_paragraphs(text: str) -> Iterable[str]:
    parts = [p.strip() for p in (text or "").splitlines() if p.strip()]
    return parts or ["(empty)"]


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
        properties["\ud2f0\ucee4"] = _rich_text_property(summary.ticker)
        market = _market_from_ticker(summary.ticker)
        if market:
            properties["\uc2dc\uc7a5"] = _select_property(market)
    if summary.presenter:
        properties["\ubc1c\ud45c\uc790"] = _select_property(summary.presenter)
    if sectors:
        properties["\uc0b0\uc5c5 \uc139\ud130"] = _multi_select_property(sectors)
    return properties


def blocks_for_post(summary: Summary, snap: PriceSnapshot, sources: list[str]) -> list[dict[str, Any]]:
    title = summary.company or "Untitled"
    if summary.ticker:
        title += f" ({summary.ticker})"

    price_line = f"{snap.ticker or summary.ticker or '-'}: {snap.status}"
    if snap.status == "ok":
        price_line = (
            f"{snap.ticker}: last {snap.last_close}, change {snap.change_pct}%, "
            f"currency {snap.currency or '-'}"
        )

    blocks: list[dict[str, Any]] = [
        _heading(1, title),
        _paragraph(f"Presenter: {summary.presenter or '-'}"),
        _heading(2, "Price snapshot"),
        _paragraph(price_line),
    ]
    if summary.target_price:
        blocks.append(_paragraph(f"Target price: {summary.target_price}"))

    for heading, body in [
        ("Company overview", summary.overview),
        ("Investment thesis", summary.thesis),
        ("Risks", summary.risks),
    ]:
        blocks.append(_heading(2, heading))
        blocks.extend(_paragraph(p) for p in _split_paragraphs(body))

    if sources:
        blocks.append(_heading(3, "Source files"))
        blocks.extend(_paragraph(f"- {source}") for source in sources)

    return blocks
