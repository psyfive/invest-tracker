"""Build invest-tracker configs from downloaded Naver Cafe attachments."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from readers.reader import SUPPORTED_EXTS


@dataclass
class ArticleBundle:
    title: str
    author: str
    url: str
    files: list[str]


def _safe_name(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text).strip()
    return text or "untitled"


def _strip_title_noise(title: str) -> str:
    title = re.sub(r"\[[^\]]+\]", " ", title)
    title = re.sub(r"\([A-Z0-9.\-]{1,12}\)", " ", title)
    title = re.sub(r"\b[A-Z]{1,6}\b", " ", title)
    title = re.sub(r"\b\d{6}(?:\.KS|\.KQ)?\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -_")
    return title or "unknown company"


def _lookup_ticker(title: str, files: list[str], ticker_map: dict[str, str]) -> str:
    haystack = " ".join([title, *files]).lower()
    for keyword, ticker in ticker_map.items():
        if keyword.lower() in haystack:
            return str(ticker)

    match = re.search(r"\b([A-Z]{1,6})\b", title)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{6})(?:\.(KS|KQ))?\b", title, flags=re.IGNORECASE)
    if match:
        return f"{match.group(1)}.{(match.group(2) or 'KS').upper()}"
    return ""


def load_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def bundles_from_manifest(manifest: dict[str, Any]) -> list[ArticleBundle]:
    bundles: list[ArticleBundle] = []
    for article in manifest.get("articles", []):
        files = [
            item["path"]
            for item in article.get("attachments", [])
            if Path(item.get("path", "")).suffix.lower() in SUPPORTED_EXTS
        ]
        if files:
            bundles.append(
                ArticleBundle(
                    title=article.get("title") or "untitled",
                    author=article.get("author") or "",
                    url=article.get("url") or "",
                    files=files,
                )
            )
    return bundles


def build_generated_config(
    base_config: dict[str, Any],
    manifest_path: str | Path,
    output_path: str | Path,
) -> Path:
    """Create a temporary config whose presentations are the downloaded articles."""
    manifest_path = Path(manifest_path)
    output_path = Path(output_path)
    automation = base_config.get("automation", {}) or {}
    ticker_map = automation.get("ticker_map", {}) or {}

    presentations: list[dict[str, Any]] = []
    for bundle in bundles_from_manifest(load_manifest(manifest_path)):
        rel_files = []
        for file_path in bundle.files:
            p = Path(file_path)
            try:
                rel_files.append(str(p.resolve().relative_to(output_path.parent.resolve())))
            except ValueError:
                rel_files.append(str(p))

        ticker = _lookup_ticker(bundle.title, rel_files, ticker_map)
        company = _strip_title_noise(bundle.title)
        presentations.append(
            {
                "presenter": bundle.author,
                "company": company,
                "ticker": ticker,
                "files": rel_files,
                "source_url": bundle.url,
            }
        )

    generated = dict(base_config)
    generated["presentations"] = presentations
    generated["output_dir"] = str(output_path.parent / "posts")
    generated["db_path"] = str(output_path.parent / "prices.db")
    generated["csv_path"] = str(output_path.parent / "prices.csv")

    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("PyYAML is required to write generated configs") from e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(generated, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return output_path


def unique_download_path(directory: Path, suggested_name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(Path(suggested_name).stem)
    suffix = Path(suggested_name).suffix
    candidate = directory / f"{stem}{suffix}"
    i = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{i}{suffix}"
        i += 1
    return candidate
