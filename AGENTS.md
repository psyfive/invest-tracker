# AGENTS.md

Guidance for agents and maintainers working in this repository.

## Project Summary

`invest-tracker` is a Python CLI for investment-study reports. It reads
prepared source files, summarizes them, renders an HTML report, optionally
publishes a Notion page, and stores yfinance price snapshots.

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
python main.py refresh-prices -c config.yaml
python main.py refresh-prices -c config.yaml --publish-notion
```

## Current Report Contract

Reports should render with:

- a `실시간 주가 추이` toggle near the top
- a target-price position indicator inside that toggle
- a company overview section
- a two-column `투자 아이디어 & 투자 리스크` table
- source file references

Do not restore the old `결론/체크포인트` section unless the product requirement
changes.

Investment ideas and risks should stay compact and bullet-oriented. LLM output
should be fact-first, numeric when possible, and every summary sentence or bullet
should end with a source marker such as `[출처: deck.pdf Slide 8]`.

## Key Modules

- `main.py`: CLI orchestration, config loading, report processing, Notion publish,
  price refresh.
- `readers/reader.py`: extracts text from PPTX, PDF, DOCX, TXT, MD, HWP/HWPX,
  and Excel files.
- `summarizer/llm_based.py`: Claude prompt and JSON parsing.
- `summarizer/rule_based.py`: offline section extraction and target-price fallback.
- `renderer/html_renderer.py`: HTML report rendering.
- `automation/notion.py`: Notion properties, blocks, page creation, and price
  toggle replacement.
- `price/fetcher.py`: yfinance snapshot fetch.
- `price/storage.py`: SQLite/CSV snapshot persistence.
- `price/indicator.py`: target-price parsing and target-position gauge logic.

## Target-Price Indicator

The target-price indicator lives in `price/indicator.py`.

Rules:

- Prefer Base/consensus target prices over generic target prices.
- Parse examples like `Base 목표가(61,000원)`, `목표주가: 95,000원`, and
  `목표주가 $180`.
- Ignore upside percentages such as `상승여력 25%`; they are not target prices.
- Use `PriceSnapshot.last_close` as current price.
- Calculation is `(current price / target price) * 100`.
- `100%` and above must render `[🔥 OVER TARGET]`.

Both HTML and Notion renderers should call the shared indicator helpers rather
than duplicating gauge logic.

## Notion Behavior

`run`, `run-folder`, and `run-reports` create Notion pages when
`--publish-notion` is passed.

`refresh-prices --publish-notion` does not rewrite the whole report. It:

1. fetches and stores fresh price snapshots,
2. finds existing pages by `company + presentation_month`,
3. archives the existing `실시간 주가 추이` toggle if present,
4. appends a newly rendered toggle.

This keeps refresh scoped to the live price section.

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

Some local Codex Windows environments may not have `python` or `py` in `PATH`.
When that happens, report the blocker instead of fabricating test results.

## Editing Notes

- Keep docs and tests updated when report structure changes.
- Keep source markers as visible text, not links, unless explicitly requested.
- Avoid broad refactors around Notion publishing; the API behavior is intentionally
  narrow and page-safe.
- Do not reintroduce Naver Cafe automation; manual file preparation is the
  current workflow.
