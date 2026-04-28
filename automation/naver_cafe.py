"""Download recent attachments from a Naver Cafe menu.

This uses a persistent Playwright browser profile. Run the login command once
manually, then scheduled runs can reuse the saved Naver session.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .pipeline import unique_download_path


def _cfg(config: dict[str, Any]) -> dict[str, Any]:
    return ((config.get("automation", {}) or {}).get("naver", {}) or {})


def _parse_date(text: str, now: datetime) -> datetime | None:
    text = text.strip()
    match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if match:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = re.search(r"\b(\d{1,2})[.:](\d{2})\b", text)
    if match:
        return now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    match = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})\.?\b", text)
    if match:
        return datetime(now.year, int(match.group(1)), int(match.group(2)))
    return None


def _recent_enough(row_text: str, days: int, now: datetime) -> bool:
    parsed = _parse_date(row_text, now)
    if parsed is None:
        return True
    return parsed >= now - timedelta(days=days)


def _require_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            "playwright is required for Naver Cafe automation. "
            "Install it with: pip install playwright && playwright install chromium"
        ) from e
    return sync_playwright


def _main_frame(page):
    for frame in page.frames:
        if frame.name == "cafe_main":
            return frame
    return page.main_frame


def _collect_article_links(frame, days: int, now: datetime) -> list[dict[str, str]]:
    articles = frame.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map(a => {
          const row = a.closest('tr,li,div') || a.parentElement;
          return {
            title: (a.innerText || a.textContent || '').trim(),
            href: a.href,
            rowText: row ? (row.innerText || row.textContent || '').trim() : '',
          };
        }).filter(x => x.href && /Article(Read|View)|articleid|articleId/i.test(x.href))
        """
    )

    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in articles:
        href = item.get("href", "")
        title = item.get("title", "").strip()
        if not href or href in seen or not title:
            continue
        if _recent_enough(item.get("rowText", ""), days, now):
            seen.add(href)
            out.append({"title": title, "url": href, "row_text": item.get("rowText", "")})
    return out


def _collect_attachment_links(frame) -> list[dict[str, str]]:
    return frame.evaluate(
        """
        () => Array.from(document.querySelectorAll('a[href]')).map(a => ({
          text: (a.innerText || a.textContent || '').trim(),
          href: a.href,
          download: a.getAttribute('download') || '',
          title: a.getAttribute('title') || '',
        })).filter(x => /download|Attach|file|첨부|다운/i.test(
          [x.text, x.href, x.download, x.title].join(' ')
        ))
        """
    )


def open_login_session(config: dict[str, Any]) -> None:
    naver = _cfg(config)
    sync_playwright = _require_playwright()
    profile_dir = Path(naver.get("browser_user_data_dir", ".browser/naver")).resolve()
    start_url = naver.get("login_url", "https://nid.naver.com/nidlogin.login")

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=False,
            accept_downloads=True,
        )
        page = context.new_page()
        page.goto(start_url, wait_until="domcontentloaded")
        print("Log in to Naver in the opened browser, then press Enter here.")
        input()
        context.close()


def download_recent_attachments(config: dict[str, Any], run_dir: str | Path) -> Path:
    naver = _cfg(config)
    if not naver.get("cafe_url"):
        raise RuntimeError("automation.naver.cafe_url is required")

    sync_playwright = _require_playwright()
    run_dir = Path(run_dir).resolve()
    profile_dir = Path(naver.get("browser_user_data_dir", ".browser/naver")).resolve()
    days = int(naver.get("days", 7))
    max_pages = int(naver.get("max_pages", 2))
    menu_name = naver.get("menu_name", "종목 분석")
    now = datetime.now()

    manifest: dict[str, Any] = {
        "downloaded_at": now.isoformat(timespec="seconds"),
        "cafe_url": naver["cafe_url"],
        "menu_name": menu_name,
        "days": days,
        "articles": [],
    }

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            str(profile_dir),
            headless=bool(naver.get("headless", True)),
            accept_downloads=True,
        )
        page = context.new_page()
        page.goto(naver["cafe_url"], wait_until="domcontentloaded")
        try:
            page.get_by_text(menu_name, exact=True).click(timeout=10000)
        except Exception:
            page.locator(f"a:has-text('{menu_name}')").first.click(timeout=10000)
        page.wait_for_timeout(1500)

        articles: list[dict[str, str]] = []
        for page_no in range(1, max_pages + 1):
            frame = _main_frame(page)
            articles.extend(_collect_article_links(frame, days, now))
            if page_no >= max_pages:
                break
            next_link = frame.locator("a:has-text('다음')").first
            if next_link.count() == 0:
                break
            try:
                next_link.click(timeout=5000)
                page.wait_for_timeout(1000)
            except Exception:
                break

        seen_urls: set[str] = set()
        for article in articles:
            if article["url"] in seen_urls:
                continue
            seen_urls.add(article["url"])
            page.goto(article["url"], wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            frame = _main_frame(page)

            author = ""
            try:
                author = frame.locator(".nick, .nickname, .writer").first.inner_text(timeout=2000).strip()
            except Exception:
                pass

            article_dir = run_dir / re.sub(r"[\\/:*?\"<>|]+", "_", article["title"])[:80]
            downloaded: list[dict[str, str]] = []
            for link in _collect_attachment_links(frame):
                href = link.get("href", "")
                if not href:
                    continue
                suggested = link.get("download") or link.get("title") or link.get("text") or "attachment"
                try:
                    locator = frame.locator(f'a[href="{href}"]').first
                    with page.expect_download(timeout=15000) as download_info:
                        locator.click(timeout=5000)
                    download = download_info.value
                    path = unique_download_path(article_dir, download.suggested_filename or suggested)
                    download.save_as(str(path))
                    downloaded.append({"name": path.name, "path": str(path)})
                    time.sleep(0.2)
                except Exception as e:
                    downloaded.append({"name": suggested, "path": "", "error": str(e)})

            if downloaded:
                manifest["articles"].append(
                    {
                        "title": article["title"],
                        "author": author,
                        "url": article["url"],
                        "attachments": downloaded,
                    }
                )

        context.close()

    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path
