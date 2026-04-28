import unittest

from automation.notion import properties_for_post
from summarizer.base import Summary


class NotionPropertiesTests(unittest.TestCase):
    def test_post_properties_include_sector_and_kospi_market(self) -> None:
        summary = Summary(
            company="\uc0bc\uc131\uc804\uc790",
            ticker="005930.KS",
            presenter="\ubc15\uc2e0\uc601",
        )

        properties = properties_for_post(summary, sectors=["IT (\uc815\ubcf4\uae30\uc220)", "\uc18c\uc7ac"])

        self.assertEqual(
            properties["\ud2f0\ucee4"],
            {"rich_text": [{"text": {"content": "005930.KS"}}]},
        )
        self.assertEqual(properties["\ubc1c\ud45c\uc790"], {"select": {"name": "\ubc15\uc2e0\uc601"}})
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


if __name__ == "__main__":
    unittest.main()
