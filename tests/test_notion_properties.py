import unittest

from automation.notion import duplicate_query_payload, properties_for_post
from summarizer.base import Summary


class NotionPropertiesTests(unittest.TestCase):
    def test_post_properties_include_sector_and_kospi_market(self) -> None:
        summary = Summary(
            company="\uc0bc\uc131\uc804\uc790",
            ticker="005930.KS",
            presenter="\ubc15\uc2e0\uc601",
            presentation_month="26.04",
        )

        properties = properties_for_post(summary, sectors=["IT (\uc815\ubcf4\uae30\uc220)", "\uc18c\uc7ac"])

        self.assertEqual(
            properties["\ud2f0\ucee4"],
            {"rich_text": [{"text": {"content": "005930.KS"}}]},
        )
        self.assertEqual(properties["\ubc1c\ud45c\uc790"], {"select": {"name": "\ubc15\uc2e0\uc601"}})
        self.assertEqual(
            properties["\ubc1c\ud45c\uc6d4"],
            {"rich_text": [{"text": {"content": "26.04"}}]},
        )
        self.assertEqual(
            properties["\uc0b0\uc5c5 \uc139\ud130"],
            {"multi_select": [{"name": "IT (\uc815\ubcf4\uae30\uc220)"}, {"name": "\uc18c\uc7ac"}]},
        )
        self.assertEqual(properties["\uc2dc\uc7a5"], {"select": {"name": "KOSPI"}})

    def test_post_properties_omit_empty_sector(self) -> None:
        summary = Summary(company="NVIDIA", ticker="NVDA", presenter="Lee")

        properties = properties_for_post(summary, sectors=[])

        self.assertNotIn("\uc0b0\uc5c5 \uc139\ud130", properties)
        self.assertNotIn("\uc2dc\uc7a5", properties)

    def test_duplicate_query_filters_by_company_and_month(self) -> None:
        payload = duplicate_query_payload("\uae30\uc5c5\uba85", "\ubc1c\ud45c\uc6d4", "\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4", "26.04")

        self.assertEqual(
            payload,
            {
                "filter": {
                    "and": [
                        {"property": "\uae30\uc5c5\uba85", "title": {"equals": "\ud55c\uc911\uc5d4\uc2dc\uc5d0\uc2a4"}},
                        {"property": "\ubc1c\ud45c\uc6d4", "rich_text": {"equals": "26.04"}},
                    ]
                },
                "page_size": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
