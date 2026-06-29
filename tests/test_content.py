import unittest
from collections import Counter

from src.content import DEMO_CONTENT


class ContentSeedTest(unittest.TestCase):
    def test_ai_term_seed_content_is_complete(self):
        required = {
            "term",
            "meaning",
            "explanation",
            "example_en",
            "example_cn",
            "question",
            "options",
            "answer",
            "difficulty",
            "topic",
        }
        terms = [item["term"] for item in DEMO_CONTENT]

        self.assertEqual(len(DEMO_CONTENT), 100)
        self.assertEqual(len(set(terms)), 100)
        self.assertEqual([term for term, count in Counter(terms).items() if count > 1], [])
        for item in DEMO_CONTENT:
            self.assertEqual(set(item), required)
            self.assertEqual(len(item["options"]), 3)
            self.assertIn(item["answer"], {"A", "B", "C"})
            self.assertIn(item["difficulty"], {1, 2, 3})
            self.assertTrue(item["term"])
            self.assertTrue(item["example_en"])


if __name__ == "__main__":
    unittest.main()
