"""Tests for the query-side zh->en bridge (docs/roadmap.md §7 Phase 5).

The bridge exists because a Chinese-only question shares no literal form with
the English implementation files. These tests pin the contract: it is additive,
query-side only, dependency-free, and never names a repository path.
"""
from __future__ import annotations

import unittest

from harness_intelligence.glossary import GLOSSARY, expand_terms
from harness_intelligence.retrieval import query_terms, split_terms


class GlossaryTests(unittest.TestCase):
    def test_a_chinese_term_expands_to_english(self) -> None:
        self.assertIn("index", expand_terms(["索引"]))
        self.assertIn("staleness", expand_terms(["陈旧"]))

    def test_expansion_is_additive_and_keeps_the_original_order(self) -> None:
        primary, expansions = split_terms("索引重建")
        self.assertTrue(primary)
        self.assertTrue(expansions)
        self.assertTrue(all(term.isascii() for term in expansions))
        self.assertEqual(query_terms("索引重建")[: len(primary)], primary)

    def test_an_unknown_term_adds_nothing(self) -> None:
        self.assertEqual(expand_terms(["完全不存在的词"]), [])

    def test_a_pure_ascii_query_is_unchanged(self) -> None:
        # An identifier the caller wrote keeps its place, and an all-English
        # query gains nothing from a Chinese dictionary.
        self.assertEqual(split_terms("load_index staleness_reason")[1], [])

    def test_entries_are_lowercase_ascii_and_never_paths(self) -> None:
        for key, values in GLOSSARY.items():
            self.assertEqual(key, key.strip(), key)
            self.assertTrue(values, key)
            for value in values:
                self.assertTrue(value.isascii(), value)
                self.assertEqual(value, value.lower(), value)
                self.assertNotIn("/", value)
                self.assertNotIn(".py", value)

    def test_the_glossary_stays_small_enough_to_review(self) -> None:
        # A hand-maintained table must stay reviewable; a runaway table would be
        # an unreviewed black box, which the roadmap explicitly rules out.
        self.assertLess(len(GLOSSARY), 200)


if __name__ == "__main__":
    unittest.main()
