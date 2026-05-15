# AGENTS.md

Guidance for agents and maintainers working in this repository.

## Project Summary

`invest-tracker` is a Python CLI for investment-study reports. It reads
manually prepared source files, extracts text, summarizes the investment case,
renders an HTML report, optionally publishes a Notion page, and stores yfinance
price snapshots.

Primary entry point:

```bash
python main.py ...
```

Important commands:

```bash
python main.py run -c config.yaml
python main.py run -c config.yaml --mode llm --publish-notion
python main.py run-folder -c config.yaml -i incoming --mode llm --publish-notion
python main.py run-reports -c config.yaml --mode llm --publish-notion
python main.py run-reports -c config.yaml --mode llm --publish-notion --force
python main.py refresh-prices -c config.yaml
python main.py refresh-prices -c config.yaml --publish-notion
python main.py refresh-notion-prices -c config.yaml
```

Naver Cafe automation is intentionally removed. The current workflow assumes
source files are prepared manually under `samples/`, `incoming/`, or `reports/`.

## Current Report Contract

Reports should render with:

- a `실시간 주가 추이` toggle near the top
- a target-price position indicator inside that toggle
- a `주가 요약 표` inside that toggle with current price, previous close,
  two-days-ago close, presentation-month last trading close, change %, and
  market cap
- a company overview section
- a two-column `투자 아이디어 & 투자 리스크` table
- source file references

Do not restore the old `결론/체크포인트` section unless the product requirement
changes.

Investment ideas and risks should stay compact and bullet-oriented. LLM output
should be fact-first, numeric when possible, and every summary sentence or
bullet should end with a source marker such as `[출처: deck.pdf Slide 8]`.

## Project Structure

- `main.py`: CLI orchestration, config loading, report processing, Notion
  publishing, price refresh, and processed-report manifest handling.
- `readers/reader.py`: extracts text from PPTX, PDF, DOCX, TXT, MD, HWP/HWPX,
  and Excel files.
- `summarizer/base.py`: `Summary` dataclass and summarizer interface.
- `summarizer/rule_based.py`: offline section extraction and target-price
  fallback.
- `summarizer/llm_based.py`: Gemini structured-output prompt, JSON parsing,
  source-label validation, and retry/debug handling.
- `summarizer/overview.py`: normalized company-overview line handling.
- `summarizer/sector_classifier.py`: optional Anthropic-based sector labels for
  Notion database properties.
- `renderer/html_renderer.py`: HTML report rendering.
- `automation/pipeline.py`: builds generated configs from prepared folders and
  report folders named `presenter,company,ticker,yy.mm`.
- `automation/notion.py`: Notion properties, blocks, page creation, duplicate
  detection, and price-toggle replacement.
- `price/fetcher.py`: yfinance snapshot fetch, recent close collection, and
  presentation-month close lookup.
- `price/storage.py`: SQLite/CSV snapshot persistence.
- `price/indicator.py`: target-price parsing and target-position gauge logic.
- `price/summary_table.py`: shared price-summary table rows and display
  formatting for HTML and Notion.
- `tests/`: unittest coverage for rendering, Notion properties, price
  indicators, readers, report-folder parsing, pipeline behavior, LLM citations,
  and sector classification.

## Price Behavior

The target-price indicator lives in `price/indicator.py`.

Rules:

- Prefer Base/consensus target prices over generic target prices.
- Parse examples like `Base 목표가(61,000원)`, `목표주가: 95,000원`, and
  `목표주가 $180`.
- Ignore upside percentages such as `상승여력 25%`; they are not target prices.
- Use `PriceSnapshot.last_close` as current price.
- Calculation is `(current price / target price) * 100`.
- `100%` and above must render `[🔥 OVER TARGET]`.

The price summary table is built through `price/summary_table.py`. Both HTML and
Notion renderers should call shared price helpers rather than duplicating gauge
or table formatting logic.

The `발표시점 종가` row is the last actual trading close in
`presentation_month`, not the calendar-month final day if the market was closed.
When a value is unavailable, render `-`.

## Notion Behavior

`run`, `run-folder`, and `run-reports` create Notion pages when
`--publish-notion` is passed.

`refresh-prices --publish-notion` does not rewrite the whole report. It:

1. fetches and stores fresh price snapshots,
2. finds existing pages by `company + presentation_month`,
3. archives the existing `실시간 주가 추이` toggle if present,
4. appends a newly rendered toggle.

`refresh-notion-prices` iterates existing Korean-market Notion pages, refreshes
their price snapshots, extracts the target price from the current toggle, and
replaces only the live price toggle.

This keeps refresh behavior scoped to the live price section.

## Testing

Preferred test command:

```bash
python -m unittest
```

Relevant tests:

- `tests/test_price_indicator.py`
- `tests/test_report_rendering.py`
- `tests/test_run_reports_skip.py`
- `tests/test_notion_properties.py`
- `tests/test_report_pipeline.py`
- `tests/test_reader.py`
- `tests/test_sector_classifier.py`
- `tests/test_llm_citations.py`
- `tests/test_overview.py`

Some local Codex Windows environments may not have `python` or `py` in `PATH`.
When that happens, report the blocker instead of fabricating test results.

## Editing Notes

- Keep docs and tests updated when report structure changes.
- Keep source markers as visible text, not links, unless explicitly requested.
- Avoid broad refactors around Notion publishing; the API behavior is
  intentionally narrow and page-safe.
- Preserve the manual file-preparation workflow. Do not reintroduce Naver Cafe
  automation.
