"""Build invest-tracker configs from manually prepared source files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from readers.reader import SUPPORTED_EXTS, iter_supported_files


@dataclass
class ArticleBundle:
    title: str
    author: str
    url: str
    files: list[str]
    ticker: str = ""
    presentation_month: str = ""


def _strip_title_noise(title: str) -> str:
    title = re.sub(r"\[[^\]]+\]", " ", title)
    title = re.sub(r"\([A-Z0-9.\-]{1,12}\)", " ", title)
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


def normalize_ticker(ticker: str) -> str:
    """Normalize user-provided tickers for yfinance.

    Korean tickers should be provided with suffixes in folder names, e.g.
    107640.kq or 005930.ks. The suffix is upper-cased for yfinance.
    """
    compact = re.sub(r"\s+", "", ticker or "")
    if not compact:
        return ""
    if "." in compact:
        symbol, suffix = compact.rsplit(".", 1)
        return f"{symbol.upper()}.{suffix.upper()}"
    return compact.upper()


def parse_report_folder_name(folder_name: str) -> dict[str, str]:
    """Parse 'presenter,company,ticker,yy.mm' report folder names."""
    parts = [part.strip() for part in folder_name.split(",")]
    if len(parts) != 4 or any(not part for part in parts):
        raise ValueError(
            "report folder name must be 'presenter,company,ticker,yy.mm'"
        )

    presenter, company, ticker, presentation_month = parts
    if not re.fullmatch(r"\d{2}\.\d{2}", presentation_month):
        raise ValueError("presentation month must use yy.mm format")

    return {
        "presenter": presenter,
        "company": company,
        "ticker": normalize_ticker(ticker),
        "presentation_month": presentation_month,
    }


def bundles_from_directory(input_dir: str | Path) -> list[ArticleBundle]:
    """Create article bundles from a manually organized input directory.

    Each child directory becomes one presentation bundle. If supported files are
    placed directly in input_dir, they are treated as a single bundle named after
    input_dir.
    """
    root = Path(input_dir).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"input directory not found: {root}")

    bundles: list[ArticleBundle] = []
    direct_files = [str(p) for p in iter_supported_files(root)]
    if direct_files:
        bundles.append(ArticleBundle(title=root.name, author="", url="", files=direct_files))

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        files = [str(p) for p in iter_supported_files(child)]
        if files:
            bundles.append(
                ArticleBundle(
                    title=child.name,
                    author="",
                    url="",
                    files=files,
                )
            )
    return bundles


def report_bundles_from_directory(input_dir: str | Path) -> list[ArticleBundle]:
    """Create bundles from report folders named presenter,company,ticker,yy.mm."""
    root = Path(input_dir).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"reports directory not found: {root}")

    bundles: list[ArticleBundle] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            parsed = parse_report_folder_name(child.name)
        except ValueError as e:
            print(f"[skip] invalid report folder '{child.name}': {e}")
            continue

        files = [str(p) for p in iter_supported_files(child)]
        if not files:
            print(f"[skip] report folder has no supported files: {child.name}")
            continue

        bundles.append(
            ArticleBundle(
                title=parsed["company"],
                author=parsed["presenter"],
                url="",
                files=files,
                ticker=parsed["ticker"],
                presentation_month=parsed["presentation_month"],
            )
        )
    return bundles


def build_config_from_bundles(
    base_config: dict[str, Any],
    bundles: list[ArticleBundle],
    output_path: str | Path,
) -> Path:
    """Create a config whose presentations are manually prepared bundles."""
    output_path = Path(output_path)
    automation = base_config.get("automation", {}) or {}
    ticker_map = automation.get("ticker_map", {}) or {}

    presentations: list[dict[str, Any]] = []
    for bundle in bundles:
        rel_files = []
        for file_path in bundle.files:
            p = Path(file_path)
            try:
                rel_files.append(str(p.resolve().relative_to(output_path.parent.resolve())))
            except ValueError:
                rel_files.append(str(p))

        ticker = bundle.ticker or _lookup_ticker(bundle.title, rel_files, ticker_map)
        company = _strip_title_noise(bundle.title)
        presentations.append(
            {
                "presenter": bundle.author,
                "company": company,
                "ticker": ticker,
                "presentation_month": bundle.presentation_month,
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


def build_config_from_directory(
    base_config: dict[str, Any],
    input_dir: str | Path,
    output_path: str | Path,
) -> Path:
    """Create a generated config from a folder of user-provided files."""
    bundles = bundles_from_directory(input_dir)
    if not bundles:
        supported = ", ".join(sorted(SUPPORTED_EXTS))
        raise RuntimeError(f"no supported files found in {input_dir} ({supported})")
    return build_config_from_bundles(base_config, bundles, output_path)


def build_report_config_from_directory(
    base_config: dict[str, Any],
    input_dir: str | Path,
    output_path: str | Path,
) -> Path:
    """Create a generated config from report folders."""
    bundles = report_bundles_from_directory(input_dir)
    if not bundles:
        supported = ", ".join(sorted(SUPPORTED_EXTS))
        raise RuntimeError(f"no valid report folders found in {input_dir} ({supported})")
    return build_config_from_bundles(base_config, bundles, output_path)
