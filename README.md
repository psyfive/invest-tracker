# invest-tracker

Investment-study report helper CLI.

It can:

- read `.pptx`, `.pdf`, `.docx`, `.txt`, `.md`, `.hwp`, `.hwpx`, `.xlsx`,
  `.xlsm`, and `.xls` source files
- summarize each source with a rule-based extractor or Gemini
- render a Notion-friendly HTML report
- publish report pages to Notion
- fetch yfinance price snapshots and store them in SQLite/CSV
- show a target-price position indicator inside the price trend toggle

Naver Cafe login and attachment download automation has been removed. Prepare
the files manually, then run the tracker against the prepared files.

## Setup

```bash
pip install -r requirements.txt
```

For LLM mode:

```bash
set GEMINI_API_KEY=...
```

For Notion publishing:

```bash
set NOTION_TOKEN=...
set NOTION_DATABASE_ID=...
```

Create a Notion integration, share the target page or database with that
integration, then fill `automation.notion.parent_page_id` or
`automation.notion.database_id` in `config.yaml`.

## Report Output

Generated reports now use this structure:

- `실시간 주가 추이` toggle at the top
- company overview with source markers
- `투자 아이디어 & 투자 리스크` as a two-column comparison table
- source file list

The old `결론/체크포인트` section is intentionally omitted.

LLM summaries use Gemini structured output with explicit source-block labels and
fact-first Korean suitable for developer and investment-study readers.
Investment ideas and risks are not fixed to three items; the tool keeps only
items supported by the materials. Summary lines should carry source markers such
as:

```text
[출처: deck.pdf p.12]
[출처: deck.pptx Slide 8]
[출처: notes.txt]
```

Renderers do not invent fallback source markers. If LLM citation validation
fails, the report is skipped and debug details are written under `output/debug/`.

## Price Trend Toggle

The `실시간 주가 추이` toggle contains:

- target-price position indicator
- current price and target price detail
- a `주가 요약 표` with current, previous close, two-days-ago close,
  presentation-month last trading close, change %, and market cap
- blank cells rendered as `-` when a price point is unavailable

Target prices are extracted from source text. Base/consensus target prices are
preferred over generic target prices:

```text
Base 목표가(61,000원)
목표주가: 95,000원
목표주가 $180
```

The indicator uses:

```text
achievement = current price / target price * 100
remaining = max(0, 100 - achievement)
```

Gauge mapping:

| Target position | Gauge |
| --- | --- |
| 0-60% | `[▓░░░░░░░░░]` |
| 61-80% | `[▓▓▓▓▓▓░░░░]` |
| 81-99.9% | `[▓▓▓▓▓▓▓▓▓░]` |
| 100%+ | `[🔥 OVER TARGET]` |

When no target price is found, the toggle shows `목표주가 없음`. When yfinance
does not return a current price, the toggle shows `현재가 없음`.

## Manual Config Run

Edit `config.yaml` directly when you already know each company, ticker,
presenter, and file path:

```bash
python main.py run -c config.yaml
python main.py run -c config.yaml --mode llm
python main.py run -c config.yaml --publish-notion
python main.py refresh-prices -c config.yaml
python main.py refresh-prices -c config.yaml --publish-notion
```

Generated HTML files are written under `output/`.

When `--publish-notion` is used with `run`, `run-folder`, or `run-reports`, the
tool also classifies each company into the standard sector list and sends Notion
database properties for ticker, presenter, one or more sectors, and Korean
market when available. Sector classification still uses Anthropic and
`ANTHROPIC_API_KEY`; it leaves the Notion sector empty if the classifier fails.

`refresh-prices --publish-notion` refreshes yfinance snapshots, finds existing
Notion pages by `company + presentation_month`, archives the existing
`실시간 주가 추이` toggle, and appends a new toggle. It updates only the price
trend toggle, not the whole Notion report body.

## Folder Run

When files are prepared manually, put each company or presentation in its own
folder:

```text
incoming/
  Samsung/
    report.pdf
    model.xlsx
    notes.md
  NVIDIA/
    deck.pptx
```

Then run:

```bash
python main.py run-folder -c config.yaml -i incoming
python main.py run-folder -c config.yaml -i incoming --mode llm --publish-notion
```

`run-folder` generates `output/generated_config.yaml`, then processes that
config. Folder names are used as the company/title. Add entries under
`automation.ticker_map` in `config.yaml` when a folder name should map to a
yfinance ticker.

If supported files are placed directly inside the input folder, the entire
folder is treated as one presentation.

## Report Folder Run

Put each report in a folder under `reports/` using this folder-name format:

```text
reports/
  Presenter,Company,107640.kq,26.04/
    deck.pptx
    workbook.xlsx
    notes.txt
```

Then run:

```bash
python main.py run-reports -c config.yaml --mode llm --publish-notion
```

`run-reports` parses presenter, company, ticker, and presentation month from the
folder name. Korean tickers should include the yfinance suffix in the folder
name, such as `107640.kq` or `005930.ks`; the script normalizes them to
`107640.KQ` and `005930.KS`.

Successful report runs are recorded in `output/processed_reports.json`. Future
`run-reports` calls skip matching presenter/company/ticker/month entries before
any LLM calls are made. Use `--force` to reprocess a report intentionally.

## Config Notes

Useful fields:

- `presentations`: explicit manual list of sources for `run`
- `summarizer.model`: Gemini model for LLM summaries, default config uses Flash
- `summarizer.sector_model`: Anthropic model for Notion sector classification
- `summarizer.max_retries`: citation/format repair attempts for LLM summaries
- `summarizer.debug_dir`: where failed LLM responses and validation details are saved
- `automation.ticker_map`: folder/name keyword to yfinance ticker mapping
- `automation.notion.parent_page_id`: create pages below a Notion page
- `automation.notion.database_id`: create pages inside a Notion database
- `automation.notion.data_source_id`: optional Notion data source override

Example presentation entry:

```yaml
presentations:
  - presenter: Park
    company: Example Corp
    ticker: 107640.KQ
    presentation_month: "26.04"
    files:
      - reports/Park,Example Corp,107640.kq,26.04/deck.pptx
      - reports/Park,Example Corp,107640.kq,26.04/notes.txt
```

## Testing

Run the unit tests with:

```bash
python -m unittest
```

In some Windows Codex workspaces the `python`/`py` launcher may not be present
in `PATH`; install Python or run the command from an environment where Python is
available.
