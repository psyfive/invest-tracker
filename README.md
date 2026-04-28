# invest-tracker

Investment-study automation CLI.

It can:

- read `.pptx`, `.pdf`, `.docx`, `.txt`, and `.md` presentation files
- summarize each presentation with a rule-based extractor or Claude
- fetch a simple yfinance price snapshot
- render a Notion-friendly HTML file
- optionally automate the monthly flow:
  1. open the Naver Cafe `종목 분석` menu
  2. download attachments from recent posts
  3. generate a temporary config
  4. run invest-tracker
  5. publish the result to Notion through the Notion API

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

For LLM mode:

```bash
set ANTHROPIC_API_KEY=...
```

For Notion publishing:

```bash
set NOTION_TOKEN=...
```

Create a Notion integration, share the target page or database with that integration,
then fill `automation.notion.parent_page_id` or `automation.notion.database_id` in
`config.yaml`.

## Manual Run

```bash
python main.py run -c config.yaml
python main.py run -c config.yaml --mode llm
python main.py run -c config.yaml --publish-notion
python main.py refresh-prices -c config.yaml
```

Generated files are written under `output/`.

## Monthly Automation

First save a Naver login session:

```bash
python main.py naver-login -c config.yaml
```

Log in in the opened browser, then return to the terminal and press Enter. The
session is stored in `.browser/naver`.

Then run the full pipeline:

```bash
python main.py auto-run -c config.yaml --mode llm --publish-notion
```

For a dry run without Notion:

```bash
python main.py auto-run -c config.yaml --mode rule
```

If downloads are already done, reuse the manifest:

```bash
python main.py auto-run -c config.yaml --manifest downloads/2026-04-28/manifest.json
```

## Scheduling on Windows

The process you described happens on the Monday after the last Sunday of a month.
The simplest robust setup is a weekly Monday Task Scheduler job that runs the
command and lets the script download only posts from the last seven days:

```powershell
cd C:\Users\Owner\Desktop\개발\invest-tracker
python main.py auto-run -c config.yaml --mode llm --publish-notion --enforce-monthly-window
```

That avoids tricky calendar logic in Task Scheduler. The task can wake up every
Monday, while `--enforce-monthly-window` makes the script skip unless the previous
day was that month’s last Sunday.

## Config Notes

Important automation fields:

- `automation.naver.cafe_url`: Naver Cafe URL
- `automation.naver.menu_name`: usually `종목 분석`
- `automation.naver.days`: recent-post window, default `7`
- `automation.ticker_map`: title/filename keyword to yfinance ticker mapping
- `automation.notion.parent_page_id`: create pages below a Notion page
- `automation.notion.database_id`: create pages inside a Notion database

Naver Cafe pages are login-protected and can change their markup. The downloader is
best-effort browser automation, so keep the first scheduled run supervised.
