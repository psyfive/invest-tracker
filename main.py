"""invest-tracker command line app."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from automation.notion import NotionClient, blocks_for_post, target_from_config
from automation.pipeline import build_config_from_directory
from price import PriceSnapshot, fetch_price_snapshot, save_snapshot
from readers import read_file
from renderer import render_post
from summarizer import Summary, get_summarizer


@dataclass
class GeneratedPost:
    summary: Summary
    price: PriceSnapshot
    html: str
    output_path: Path
    sources: list[str]


def _load_config(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as e:
            raise RuntimeError("PyYAML is not installed; run pip install pyyaml") from e
        return yaml.safe_load(text) or {}
    if suffix == ".json":
        return json.loads(text)
    raise ValueError(f"unsupported config extension: {suffix}")


def _safe_filename(text: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", text).strip()
    return text or "untitled"


def _resolve_config_path(base_dir: Path, value: str | Path, default: str) -> Path:
    path = Path(value or default)
    if not path.is_absolute():
        path = base_dir / path
    return path


def _gather_text(file_paths: list[str], base_dir: Path) -> tuple[str, list[str]]:
    chunks: list[str] = []
    used: list[str] = []
    for file_path in file_paths:
        path = Path(file_path)
        if not path.is_absolute():
            path = (base_dir / path).resolve()
        if not path.exists():
            chunks.append(f"[file not found: {file_path}]")
            continue
        try:
            text = read_file(path)
        except Exception as e:
            chunks.append(f"[{path.name} read failed: {e}]")
            continue
        if text.strip():
            chunks.append(f"### File: {path.name}\n{text}")
            used.append(path.name)
    return "\n\n".join(chunks), used


def process_config(
    config: dict[str, Any],
    base_dir: Path,
    mode_override: str | None = None,
    presenter_filter: str | None = None,
    ticker_filter: str | None = None,
) -> list[GeneratedPost]:
    output_dir = _resolve_config_path(base_dir, config.get("output_dir", "output"), "output")
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = _resolve_config_path(base_dir, config.get("db_path", "output/prices.db"), "output/prices.db")
    csv_path = _resolve_config_path(base_dir, config.get("csv_path", "output/prices.csv"), "output/prices.csv")

    summ_cfg = config.get("summarizer", {}) or {}
    mode = mode_override or summ_cfg.get("mode", "rule")
    summ_kwargs: dict[str, Any] = {}
    if mode == "llm" and "model" in summ_cfg:
        summ_kwargs["model"] = summ_cfg["model"]
    summarizer = get_summarizer(mode, **summ_kwargs)
    print(f"[config] summarizer mode: {mode}")

    presentations = config.get("presentations", []) or []
    if presenter_filter:
        presentations = [p for p in presentations if p.get("presenter", "") == presenter_filter]
    if ticker_filter:
        presentations = [p for p in presentations if p.get("ticker", "") == ticker_filter]
    if not presentations:
        raise RuntimeError("no presentations to process")

    posts: list[GeneratedPost] = []
    for entry in presentations:
        company = (entry.get("company") or "").strip()
        ticker = (entry.get("ticker") or "").strip()
        presenter = (entry.get("presenter") or "").strip()
        files = entry.get("files", []) or []
        if not company:
            print("[skip] presentation has no company")
            continue

        print(f"\nProcessing {company} ({ticker or 'no ticker'})")
        text, used_files = _gather_text(files, base_dir)
        if not text.strip():
            print(f"  [warning] no readable text from {files}")

        try:
            summary = summarizer.summarize(text, company=company, ticker=ticker, presenter=presenter)
        except Exception as e:
            print(f"  [error] summarize failed: {e}", file=sys.stderr)
            continue

        price = fetch_price_snapshot(ticker)
        try:
            save_snapshot(price, db_path=db_path, csv_path=csv_path)
            print(f"  price: {price.status} (last={price.last_close})")
        except Exception as e:
            print(f"  [warning] price save failed: {e}", file=sys.stderr)

        source_labels = list(used_files)
        if entry.get("source_url"):
            source_labels.append(str(entry["source_url"]))

        try:
            html_doc = render_post(summary, price, sources=source_labels)
        except Exception as e:
            print(f"  [error] render failed: {e}", file=sys.stderr)
            continue

        output_path = output_dir / (_safe_filename(f"{company}_{ticker or 'noticker'}") + ".html")
        output_path.write_text(html_doc, encoding="utf-8")
        print(f"  wrote {output_path}")
        posts.append(GeneratedPost(summary, price, html_doc, output_path, source_labels))

    return posts


def publish_to_notion(config: dict[str, Any], posts: list[GeneratedPost]) -> list[str]:
    target = target_from_config(config)
    if target is None:
        raise RuntimeError("Notion config is missing")
    client = NotionClient(target.token)
    page_ids: list[str] = []
    for post in posts:
        title = post.summary.company
        if post.summary.ticker:
            title += f" ({post.summary.ticker})"
        page_id = client.create_page(
            target,
            title=title,
            children=blocks_for_post(post.summary, post.price, post.sources),
        )
        page_ids.append(page_id)
        print(f"  published to Notion: {title} ({page_id})")
    return page_ids


def cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    posts = process_config(
        config,
        config_path.parent,
        mode_override=args.mode,
        presenter_filter=args.presenter,
        ticker_filter=args.ticker,
    )
    if args.publish_notion:
        publish_to_notion(config, posts)
    print(f"\nDone: {len(posts)} post(s)")
    return 0 if posts else 1


def cmd_refresh_prices(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    base_dir = config_path.parent
    db_path = _resolve_config_path(base_dir, config.get("db_path", "output/prices.db"), "output/prices.db")
    csv_path = _resolve_config_path(base_dir, config.get("csv_path", "output/prices.csv"), "output/prices.csv")

    tickers = sorted(
        {
            (entry.get("ticker") or "").strip()
            for entry in config.get("presentations", []) or []
            if (entry.get("ticker") or "").strip()
        }
    )
    if not tickers:
        print("no tickers found in config", file=sys.stderr)
        return 1

    for ticker in tickers:
        snap = fetch_price_snapshot(ticker)
        save_snapshot(snap, db_path=db_path, csv_path=csv_path)
        print(f"{ticker:14} {snap.status} last={snap.last_close}")
    return 0


def cmd_run_folder(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    base_dir = config_path.parent
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = base_dir / input_dir
    output_dir = Path(args.output_dir or config.get("output_dir", "output"))
    if not output_dir.is_absolute():
        output_dir = base_dir / output_dir

    generated_config_path = output_dir / "generated_config.yaml"
    build_config_from_directory(config, input_dir, generated_config_path)
    print(f"generated config: {generated_config_path}")
    generated_config = _load_config(generated_config_path)

    posts = process_config(
        generated_config,
        generated_config_path.parent,
        mode_override=args.mode,
        presenter_filter=args.presenter,
        ticker_filter=args.ticker,
    )
    if args.publish_notion:
        publish_to_notion(generated_config, posts)

    print(f"\nDone: {len(posts)} post(s)")
    return 0 if posts else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="invest-tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="summarize configured presentation files")
    p_run.add_argument("--config", "-c", required=True)
    p_run.add_argument("--mode", choices=["rule", "llm"])
    p_run.add_argument("--presenter")
    p_run.add_argument("--ticker")
    p_run.add_argument("--publish-notion", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_ref = sub.add_parser("refresh-prices", help="refresh only price snapshots")
    p_ref.add_argument("--config", "-c", required=True)
    p_ref.set_defaults(func=cmd_refresh_prices)

    p_folder = sub.add_parser("run-folder", help="summarize manually prepared files from a folder")
    p_folder.add_argument("--config", "-c", required=True)
    p_folder.add_argument("--input-dir", "-i", required=True)
    p_folder.add_argument("--mode", choices=["rule", "llm"])
    p_folder.add_argument("--presenter")
    p_folder.add_argument("--ticker")
    p_folder.add_argument("--output-dir")
    p_folder.add_argument("--publish-notion", action="store_true")
    p_folder.set_defaults(func=cmd_run_folder)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
