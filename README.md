# invest-tracker

Investment-study helper CLI.

It can:

- read `.pptx`, `.pdf`, `.docx`, `.txt`, and `.md` source files
- summarize each source with a rule-based extractor or Claude
- fetch a simple yfinance price snapshot
- render a Notion-friendly HTML file
- optionally publish the result to Notion through the Notion API

Naver Cafe login and attachment download automation has been removed. Prepare the
files manually, then run the tracker against the prepared files.

## Setup

```bash
pip install -r requirements.txt
```

For LLM mode:

```bash
set ANTHROPIC_API_KEY=...
```

For Notion publishing:

```bash
set NOTION_TOKEN=...
set NOTION_DATABASE_ID=...
```

Create a Notion integration, share the target page or database with that
integration, then fill `automation.notion.parent_page_id` or
`automation.notion.database_id` in `config.yaml`.

## Manual Config Run

Edit `config.yaml` directly when you already know each company, ticker, presenter,
and file path:

```bash
python main.py run -c config.yaml
python main.py run -c config.yaml --mode llm
python main.py run -c config.yaml --publish-notion
python main.py refresh-prices -c config.yaml
```

Generated files are written under `output/`.

When `--publish-notion` is used, the tool also classifies each company into the
standard sector list and sends Notion database properties for ticker, presenter,
one or more sectors, and Korean market when available. Sector classification
uses the same Anthropic API key as LLM summarization and leaves the Notion sector
empty if the classifier fails.

## Folder Run

When files are prepared manually, put each company or presentation in its own
folder:

```text
incoming/
  Samsung/
    report.pdf
    notes.md
  NVIDIA/
    deck.pptx
```

Then run:

```bash
python main.py run-folder -c config.yaml -i incoming
python main.py run-folder -c config.yaml -i incoming --mode llm --publish-notion
```

`run-folder` generates `output/generated_config.yaml`, then processes that config.
Folder names are used as the company/title. Add entries under
`automation.ticker_map` in `config.yaml` when a folder name should map to a
yfinance ticker.

If supported files are placed directly inside the input folder, the entire folder
is treated as one presentation.

## Report Folder Run

Put each report in a folder under `reports/` using:

```text
reports/
  박신영,한중엔시에스,107640.kq,26.04/
    deck.pptx
    notes.txt
```

Then run:

```bash
python main.py run-reports -c config.yaml --mode llm --publish-notion
```

`run-reports` parses presenter, company, ticker, and presentation month from
the folder name. Korean tickers should include the yfinance suffix in the folder
name, such as `107640.kq` or `005930.ks`; the script normalizes them to
`107640.KQ` and `005930.KS`.

Successful report runs are recorded in `output/processed_reports.json`. Future
`run-reports` calls skip matching presenter/company/ticker/month entries before
any LLM calls are made. Use `--force` to reprocess a report intentionally.

## Chat-Based Workflow

Going forward, send the cleaned files in chat. I can place them into an `incoming/`
folder, update ticker mappings if needed, and run `run-folder` or the regular
`run` command from there.

## Config Notes

Useful fields:

- `presentations`: explicit manual list of sources for `run`
- `automation.ticker_map`: folder/name keyword to yfinance ticker mapping
- `automation.notion.parent_page_id`: create pages below a Notion page
- `automation.notion.database_id`: create pages inside a Notion database
