"""invest-tracker command line app."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from automation.notion import (
    NotionClient,
    blocks_for_post,
    is_korean_market_page,
    page_title,
    page_ticker,
    price_trend_toggle_block,
    properties_for_post,
    target_from_config,
)
from automation.pipeline import build_config_from_directory, build_report_config_from_directory
from price import PriceSnapshot, extract_target_price, fetch_price_snapshot, save_snapshot
from readers import read_file
from renderer import render_post
from summarizer import SectorClassifier, Summary, get_summarizer


@dataclass
class GeneratedPost:
    summary: Summary
    price: PriceSnapshot
    html: str
    output_path: Path
    sources: list[str]
    sectors: list[str]


REPORT_MANIFEST_NAME = "processed_reports.json"
REPORT_MANIFEST_VERSION = 1


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


def _report_manifest_path(output_dir: Path) -> Path:
    return output_dir / REPORT_MANIFEST_NAME


def _report_key(presenter: str, company: str, ticker: str, presentation_month: str) -> str:
    return "|".join(
        [
            presenter.strip(),
            company.strip(),
            ticker.strip().upper(),
            presentation_month.strip(),
        ]
    )


def _report_key_for_entry(entry: dict[str, Any]) -> str:
    return _report_key(
        str(entry.get("presenter") or ""),
        str(entry.get("company") or ""),
        str(entry.get("ticker") or ""),
        str(entry.get("presentation_month") or ""),
    )


def _report_key_for_post(post: GeneratedPost) -> str:
    return _report_key(
        post.summary.presenter,
        post.summary.company,
        post.summary.ticker,
        post.summary.presentation_month,
    )


def load_processed_report_manifest(path: Path) -> dict[str, Any]:
    """Load the local report completion manifest."""
    if not path.exists():
        return {"version": REPORT_MANIFEST_VERSION, "reports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warning] failed to read report manifest {path}: {e}", file=sys.stderr)
        return {"version": REPORT_MANIFEST_VERSION, "reports": {}}

    if not isinstance(data, dict) or not isinstance(data.get("reports"), dict):
        print(f"[warning] invalid report manifest format: {path}", file=sys.stderr)
        return {"version": REPORT_MANIFEST_VERSION, "reports": {}}
    data.setdefault("version", REPORT_MANIFEST_VERSION)
    return data


def skip_processed_reports(config: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Remove report presentations that were already completed locally."""
    reports = manifest.get("reports") or {}
    kept: list[dict[str, Any]] = []
    for entry in config.get("presentations", []) or []:
        key = _report_key_for_entry(entry)
        if key and key in reports:
            print(
                "[skip] report already processed locally: "
                f"{entry.get('company', '')} {entry.get('presentation_month', '')}"
            )
            continue
        kept.append(entry)

    filtered = dict(config)
    filtered["presentations"] = kept
    return filtered


def save_processed_report_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def record_processed_reports(path: Path, posts: list[GeneratedPost]) -> None:
    """Record successfully completed reports after processing and optional publishing."""
    if not posts:
        return

    manifest = load_processed_report_manifest(path)
    reports = manifest.setdefault("reports", {})
    processed_at = datetime.now(timezone.utc).isoformat()
    for post in posts:
        key = _report_key_for_post(post)
        if not key:
            continue
        reports[key] = {
            "company": post.summary.company,
            "ticker": post.summary.ticker,
            "presenter": post.summary.presenter,
            "presentation_month": post.summary.presentation_month,
            "output_path": str(post.output_path),
            "sources": post.sources,
            "processed_at": processed_at,
        }
    manifest["version"] = REPORT_MANIFEST_VERSION
    save_processed_report_manifest(path, manifest)


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


def _target_price_text_from_source(text: str, fallback: str = "") -> str:
    target = extract_target_price(text)
    if target is not None:
        return target.display
    return fallback.strip()


def process_config(
    config: dict[str, Any],
    base_dir: Path,
    mode_override: str | None = None,
    presenter_filter: str | None = None,
    ticker_filter: str | None = None,
    classify_sector: bool = False,
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

    sector_classifier: SectorClassifier | None = None
    if classify_sector:
        sector_classifier = SectorClassifier(model=summ_cfg.get("model", "claude-sonnet-4-5"))

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
        presentation_month = (entry.get("presentation_month") or "").strip()
        files = entry.get("files", []) or []
        if not company:
            print("[skip] presentation has no company")
            continue

        print(f"\nProcessing {company} ({ticker or 'no ticker'})")
        text, used_files = _gather_text(files, base_dir)
        if not text.strip():
            print(f"  [warning] no readable text from {files}")

        try:
            summary = summarizer.summarize(
                text,
                company=company,
                ticker=ticker,
                presenter=presenter,
                presentation_month=presentation_month,
            )
        except Exception as e:
            print(f"  [error] summarize failed: {e}", file=sys.stderr)
            continue
        summary.target_price = _target_price_text_from_source(text, summary.target_price)

        sectors: list[str] = []
        if sector_classifier is not None:
            try:
                sectors = sector_classifier.classify(company=company, ticker=ticker, body=text)
                if sectors:
                    print(f"  sectors: {', '.join(sectors)}")
                else:
                    print("  [warning] sector classification returned no valid sectors", file=sys.stderr)
            except Exception as e:
                print(f"  [warning] sector classification failed: {e}", file=sys.stderr)

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
        posts.append(GeneratedPost(summary, price, html_doc, output_path, source_labels, sectors))

    return posts


def publish_to_notion(config: dict[str, Any], posts: list[GeneratedPost]) -> list[str]:
    target = target_from_config(config)
    if target is None:
        raise RuntimeError("Notion config is missing")
    client = NotionClient(target.token)
    page_ids: list[str] = []
    for post in posts:
        title = post.summary.company
        if target.database_id and post.summary.presentation_month:
            existing_page_id = client.find_existing_page(
                target,
                post.summary.company,
                post.summary.presentation_month,
            )
            if existing_page_id:
                print(
                    "  [skip] Notion page already exists: "
                    f"{post.summary.company} {post.summary.presentation_month} ({existing_page_id})"
                )
                continue

        page_id = client.create_page(
            target,
            title=title,
            children=blocks_for_post(post.summary, post.price, post.sources),
            extra_properties=properties_for_post(post.summary, post.sectors),
        )
        page_ids.append(page_id)
        print(f"  published to Notion: {title} ({page_id})")
    return page_ids


def skip_existing_notion_reports(config: dict[str, Any]) -> dict[str, Any]:
    """Remove report presentations that already exist in the target Notion DB."""
    target = target_from_config(config)
    if target is None:
        raise RuntimeError("Notion config is missing")
    if not target.database_id:
        return config

    client = NotionClient(target.token)
    kept: list[dict[str, Any]] = []
    for entry in config.get("presentations", []) or []:
        company = (entry.get("company") or "").strip()
        presentation_month = (entry.get("presentation_month") or "").strip()
        if not company or not presentation_month:
            kept.append(entry)
            continue

        existing_page_id = client.find_existing_page(target, company, presentation_month)
        if existing_page_id:
            print(
                "[skip] Notion page already exists before processing: "
                f"{company} {presentation_month} ({existing_page_id})"
            )
            continue
        kept.append(entry)

    filtered = dict(config)
    filtered["presentations"] = kept
    return filtered


def cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    posts = process_config(
        config,
        config_path.parent,
        mode_override=args.mode,
        presenter_filter=args.presenter,
        ticker_filter=args.ticker,
        classify_sector=args.publish_notion,
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

    presentations = config.get("presentations", []) or []
    tickers = sorted({(entry.get("ticker") or "").strip() for entry in presentations if (entry.get("ticker") or "").strip()})
    if not tickers:
        print("no tickers found in config", file=sys.stderr)
        return 1

    snapshots: dict[str, PriceSnapshot] = {}
    for ticker in tickers:
        snap = fetch_price_snapshot(ticker)
        snapshots[ticker] = snap
        save_snapshot(snap, db_path=db_path, csv_path=csv_path)
        print(f"{ticker:14} {snap.status} last={snap.last_close}")

    if getattr(args, "publish_notion", False):
        target = target_from_config(config)
        if target is None:
            raise RuntimeError("Notion config is missing")
        client = NotionClient(target.token)
        updated = 0
        for entry in presentations:
            company = (entry.get("company") or "").strip()
            presentation_month = (entry.get("presentation_month") or "").strip()
            ticker = (entry.get("ticker") or "").strip()
            if not company or not presentation_month:
                print(
                    f"  [skip] Notion price toggle refresh needs company and presentation_month: {company or ticker}",
                    file=sys.stderr,
                )
                continue
            snap = snapshots.get(ticker)
            if snap is None:
                continue
            text, _used_files = _gather_text(entry.get("files", []) or [], base_dir)
            target_price_text = _target_price_text_from_source(text)
            page_id = client.find_existing_page(target, company, presentation_month)
            if not page_id:
                print(f"  [skip] Notion page not found: {company} {presentation_month}", file=sys.stderr)
                continue
            client.replace_price_trend_toggle(page_id, price_trend_toggle_block(snap, target_price_text))
            updated += 1
            print(f"  updated Notion price toggle: {company} {presentation_month}")
        print(f"  Notion price toggle updates: {updated}")
    return 0


def cmd_refresh_notion_prices(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    base_dir = config_path.parent
    db_path = _resolve_config_path(base_dir, config.get("db_path", "output/prices.db"), "output/prices.db")
    csv_path = _resolve_config_path(base_dir, config.get("csv_path", "output/prices.csv"), "output/prices.csv")

    target = target_from_config(config)
    if target is None:
        raise RuntimeError("Notion config is missing")

    client = NotionClient(target.token)
    pages = client.iter_database_pages(target)
    updated = 0
    skipped = 0

    for page in pages:
        page_id = str(page.get("id") or "")
        ticker = page_ticker(page)
        company = page_title(page, target.title_property) or page_id
        if not page_id or not ticker or not is_korean_market_page(page):
            skipped += 1
            continue

        snap = fetch_price_snapshot(ticker)
        save_snapshot(snap, db_path=db_path, csv_path=csv_path)
        target_price_text = client.extract_price_trend_target_text(page_id)
        client.replace_price_trend_toggle(page_id, price_trend_toggle_block(snap, target_price_text))
        updated += 1
        print(f"updated {company} ({ticker}): {snap.status} last={snap.last_close}")

    print(f"Notion Korean-market price toggle updates: {updated}; skipped: {skipped}")
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
        classify_sector=args.publish_notion,
    )
    if args.publish_notion:
        publish_to_notion(generated_config, posts)

    print(f"\nDone: {len(posts)} post(s)")
    return 0 if posts else 1


def cmd_run_reports(args: argparse.Namespace) -> int:
    config_path = Path(args.config).resolve()
    config = _load_config(config_path)
    base_dir = config_path.parent
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = base_dir / input_dir
    output_dir = Path(args.output_dir or config.get("output_dir", "output"))
    if not output_dir.is_absolute():
        output_dir = base_dir / output_dir

    generated_config_path = output_dir / "generated_reports_config.yaml"
    manifest_path = _report_manifest_path(output_dir)
    build_report_config_from_directory(config, input_dir, generated_config_path)
    print(f"generated report config: {generated_config_path}")
    generated_config = _load_config(generated_config_path)

    if not getattr(args, "force", False):
        manifest = load_processed_report_manifest(manifest_path)
        generated_config = skip_processed_reports(generated_config, manifest)
        if not (generated_config.get("presentations") or []):
            print("\nDone: 0 report post(s); all reports already processed locally")
            return 0

    if args.publish_notion:
        generated_config = skip_existing_notion_reports(generated_config)
        if not (generated_config.get("presentations") or []):
            print("\nDone: 0 report post(s); all reports already exist in Notion")
            return 0

    posts = process_config(
        generated_config,
        generated_config_path.parent,
        mode_override=args.mode,
        presenter_filter=args.presenter,
        ticker_filter=args.ticker,
        classify_sector=args.publish_notion,
    )
    if args.publish_notion:
        publish_to_notion(generated_config, posts)
    record_processed_reports(manifest_path, posts)

    print(f"\nDone: {len(posts)} report post(s)")
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
    p_ref.add_argument("--publish-notion", action="store_true")
    p_ref.set_defaults(func=cmd_refresh_prices)

    p_ref_notion = sub.add_parser("refresh-notion-prices", help="refresh price toggles for all Korean-market Notion pages")
    p_ref_notion.add_argument("--config", "-c", required=True)
    p_ref_notion.set_defaults(func=cmd_refresh_notion_prices)

    p_folder = sub.add_parser("run-folder", help="summarize manually prepared files from a folder")
    p_folder.add_argument("--config", "-c", required=True)
    p_folder.add_argument("--input-dir", "-i", required=True)
    p_folder.add_argument("--mode", choices=["rule", "llm"])
    p_folder.add_argument("--presenter")
    p_folder.add_argument("--ticker")
    p_folder.add_argument("--output-dir")
    p_folder.add_argument("--publish-notion", action="store_true")
    p_folder.set_defaults(func=cmd_run_folder)

    p_reports = sub.add_parser("run-reports", help="summarize report folders named presenter,company,ticker,yy.mm")
    p_reports.add_argument("--config", "-c", required=True)
    p_reports.add_argument("--input-dir", "-i", default="reports")
    p_reports.add_argument("--mode", choices=["rule", "llm"])
    p_reports.add_argument("--presenter")
    p_reports.add_argument("--ticker")
    p_reports.add_argument("--output-dir")
    p_reports.add_argument("--publish-notion", action="store_true")
    p_reports.add_argument("--force", action="store_true", help="reprocess reports already recorded locally")
    p_reports.set_defaults(func=cmd_run_reports)

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        pass
    else:
        load_dotenv()

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
