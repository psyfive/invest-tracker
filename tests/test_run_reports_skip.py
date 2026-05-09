import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.notion import NotionTarget
from main import (
    GeneratedPost,
    cmd_run_reports,
    load_processed_report_manifest,
    record_processed_reports,
    skip_existing_notion_reports,
    skip_processed_reports,
)
from price import PriceSnapshot
from summarizer import Summary


class FakeNotionClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def find_existing_page(self, target: NotionTarget, company: str, presentation_month: str) -> str | None:
        if company == "A Corp" and presentation_month == "26.04":
            return "page-1"
        return None


class RunReportsSkipTests(unittest.TestCase):
    def test_skip_existing_notion_reports_removes_duplicates_before_processing(self) -> None:
        config = {
            "presentations": [
                {"company": "A Corp", "presentation_month": "26.04", "ticker": "000001.KS"},
                {"company": "B Corp", "presentation_month": "26.04", "ticker": "000002.KQ"},
            ]
        }

        with (
            patch("main.target_from_config", return_value=NotionTarget(token="token", database_id="db")),
            patch("main.NotionClient", FakeNotionClient),
        ):
            filtered = skip_existing_notion_reports(config)

        self.assertEqual(
            filtered["presentations"],
            [{"company": "B Corp", "presentation_month": "26.04", "ticker": "000002.KQ"}],
        )

    def test_skip_processed_reports_removes_manifest_matches_before_processing(self) -> None:
        config = {
            "presentations": [
                {
                    "presenter": "Kim",
                    "company": "A Corp",
                    "presentation_month": "26.04",
                    "ticker": "000001.KS",
                },
                {
                    "presenter": "Lee",
                    "company": "B Corp",
                    "presentation_month": "26.04",
                    "ticker": "000002.KQ",
                },
            ]
        }
        manifest = {
            "version": 1,
            "reports": {
                "Kim|A Corp|000001.KS|26.04": {"company": "A Corp"},
            },
        }

        filtered = skip_processed_reports(config, manifest)

        self.assertEqual(
            filtered["presentations"],
            [
                {
                    "presenter": "Lee",
                    "company": "B Corp",
                    "presentation_month": "26.04",
                    "ticker": "000002.KQ",
                }
            ],
        )

    def test_record_processed_reports_updates_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "processed_reports.json"
            post = GeneratedPost(
                summary=Summary(
                    company="A Corp",
                    ticker="000001.KS",
                    presenter="Kim",
                    presentation_month="26.04",
                ),
                price=PriceSnapshot(ticker="000001.KS", fetched_at="now"),
                html="<html></html>",
                output_path=Path(tmp) / "A Corp_000001.KS.html",
                sources=["notes.txt"],
                sectors=[],
            )

            record_processed_reports(manifest_path, [post])
            manifest = load_processed_report_manifest(manifest_path)

        record = manifest["reports"]["Kim|A Corp|000001.KS|26.04"]
        self.assertEqual(record["company"], "A Corp")
        self.assertEqual(record["sources"], ["notes.txt"])
        self.assertIn("processed_at", record)

    def test_run_reports_force_ignores_local_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "config.yaml"
            reports_dir = root / "reports"
            output_dir = root / "output"
            reports_dir.mkdir()
            output_dir.mkdir()
            config_path.write_text("output_dir: output\n", encoding="utf-8")
            (output_dir / "processed_reports.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "reports": {
                            "Kim|A Corp|000001.KS|26.04": {"company": "A Corp"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            def write_generated_config(_config, _input_dir, output_path):
                Path(output_path).write_text(
                    """
presentations:
  - presenter: Kim
    company: A Corp
    ticker: 000001.KS
    presentation_month: '26.04'
    files: []
output_dir: posts
db_path: prices.db
csv_path: prices.csv
""".strip(),
                    encoding="utf-8",
                )

            post = GeneratedPost(
                summary=Summary(
                    company="A Corp",
                    ticker="000001.KS",
                    presenter="Kim",
                    presentation_month="26.04",
                ),
                price=PriceSnapshot(ticker="000001.KS", fetched_at="now"),
                html="<html></html>",
                output_path=output_dir / "posts" / "A Corp_000001.KS.html",
                sources=[],
                sectors=[],
            )
            args = argparse.Namespace(
                config=str(config_path),
                input_dir=str(reports_dir),
                output_dir=str(output_dir),
                mode=None,
                presenter=None,
                ticker=None,
                publish_notion=False,
                force=True,
            )

            with (
                patch("main.build_report_config_from_directory", side_effect=write_generated_config),
                patch("main.process_config", return_value=[post]) as process_config,
            ):
                code = cmd_run_reports(args)

        self.assertEqual(code, 0)
        process_config.assert_called_once()


if __name__ == "__main__":
    unittest.main()
