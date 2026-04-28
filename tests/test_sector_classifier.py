import unittest

from summarizer.sector_classifier import (
    SECTOR_TAXONOMY,
    SectorClassifier,
    build_sector_prompt,
    parse_sector_response,
)


IT = "IT (\uc815\ubcf4\uae30\uc220)"
FINANCE = "\uae08\uc735"
HEALTHCARE = "\uac74\uac15\uad00\ub9ac"
DISCRETIONARY = "\uacbd\uae30\uad00\ub828\uc18c\ube44\uc7ac"
UTILITIES = "\uc720\ud2f8\ub9ac\ud2f0"


class FakeSectorClassifier(SectorClassifier):
    RESPONSES = {
        "\uc0bc\uc131\uc804\uc790": {"sectors": [IT]},
        "NVIDIA": {"sectors": [IT]},
        "KB\uae08\uc735": {"sectors": [FINANCE]},
        "\uc140\ud2b8\ub9ac\uc628": {"sectors": [HEALTHCARE]},
        "\ud604\ub300\ucc28": {"sectors": [DISCRETIONARY]},
        "\ud55c\uad6d\uc804\ub825": {"sectors": [UTILITIES]},
    }

    def _call_api(self, prompt: str) -> str:
        for company, response in self.RESPONSES.items():
            if company in prompt:
                sectors = ", ".join(f'"{sector}"' for sector in response["sectors"])
                return f'{{"sectors": [{sectors}]}}'
        return '{"sectors": ["unknown"]}'


class SectorClassifierTests(unittest.TestCase):
    def test_prompt_contains_allowed_sector_taxonomy(self) -> None:
        prompt = build_sector_prompt(
            "\uc0bc\uc131\uc804\uc790",
            "005930.KS",
            "\ubc18\ub3c4\uccb4\uc640 \uc804\uc790\uc7a5\ube44",
        )
        for sector, industries in SECTOR_TAXONOMY.items():
            self.assertIn(sector, prompt)
            self.assertIn(industries, prompt)

    def test_parse_rejects_values_outside_taxonomy(self) -> None:
        self.assertEqual(parse_sector_response(f'{{"sectors": ["{IT}", "unknown"]}}'), [IT])
        self.assertEqual(parse_sector_response(f'{{"sector": "{IT}"}}'), [IT])
        self.assertEqual(parse_sector_response('{"sectors": ["unknown"]}'), [])
        self.assertEqual(parse_sector_response("not json"), [])

    def test_parse_accepts_multiple_valid_sectors_once(self) -> None:
        self.assertEqual(
            parse_sector_response(f'{{"sectors": ["{IT}", "{FINANCE}", "{IT}"]}}'),
            [IT, FINANCE],
        )

    def test_llm_classification_plumbing_with_expected_examples(self) -> None:
        classifier = FakeSectorClassifier(api_key="test")
        cases = {
            "\uc0bc\uc131\uc804\uc790": IT,
            "NVIDIA": IT,
            "KB\uae08\uc735": FINANCE,
            "\uc140\ud2b8\ub9ac\uc628": HEALTHCARE,
            "\ud604\ub300\ucc28": DISCRETIONARY,
            "\ud55c\uad6d\uc804\ub825": UTILITIES,
        }
        for company, expected_sector in cases.items():
            with self.subTest(company=company):
                self.assertEqual(classifier.classify(company, body=company), [expected_sector])


if __name__ == "__main__":
    unittest.main()
