from __future__ import annotations

import unittest

from harness_intelligence.terms import (
    MAX_TERMS,
    bridged_terms,
    content_pattern,
    extract_terms,
    identifier_parts,
)


def varied_runs(count: int) -> str:
    """``count`` distinct three-character CJK runs.

    Repeating one run would collapse into a handful of unique n-grams, so the
    characters have to vary to exercise the cap.
    """
    return " ".join(
        "".join(chr(0x4E00 + (index * 3 + step) % 400) for step in range(3))
        for index in range(count)
    )


class ExtractTermsTests(unittest.TestCase):
    """The query side of matching: what a prompt is turned into."""

    def test_chinese_run_becomes_overlapping_ngrams(self) -> None:
        # A whole run like "重建索引" never appears literally in English source or
        # in a differently worded doc, so it has to be split to match anything.
        self.assertEqual(
            extract_terms("重建索引"), ["重建", "建索", "索引", "重建索", "建索引"]
        )

    def test_single_characters_are_not_terms(self) -> None:
        # One CJK character matches almost every Chinese line, so the shortest term
        # is a bigram. The same two-character floor applies to ASCII.
        self.assertEqual(extract_terms("中"), [])
        self.assertEqual(extract_terms("a"), [])
        self.assertEqual(extract_terms("ab"), ["ab"])

    def test_ascii_terms_are_kept_whole_and_lowercased(self) -> None:
        self.assertEqual(
            extract_terms("Fix load_index In INDEX_VERSION"),
            ["fix", "load_index", "in", "index_version"],
        )

    def test_terms_are_deduplicated_in_first_seen_order(self) -> None:
        self.assertEqual(extract_terms("索引 then 索引"), ["then", "索引"])

    def test_ascii_terms_come_first_and_survive_the_cap(self) -> None:
        # The cap exists to bound the per-line scan. It must never be able to drop
        # an identifier the caller spelled out.
        terms = extract_terms("keep_me " + varied_runs(200))
        self.assertEqual(len(terms), MAX_TERMS)
        self.assertEqual(terms[0], "keep_me")

    def test_set_based_callers_can_opt_out_of_the_cap(self) -> None:
        self.assertGreater(len(extract_terms(varied_runs(200), limit=None)), MAX_TERMS)
        self.assertEqual(len(extract_terms(varied_runs(200))), MAX_TERMS)


class BridgedTermsTests(unittest.TestCase):
    """The query-side bridge from a Chinese prompt to English source."""

    def test_chinese_words_gain_their_english_lookups(self) -> None:
        # The gap this guards: "索引陈旧检测" n-grams never overlap indexer.py or
        # staleness_reason, so a Chinese-only task could not reach English code.
        self.assertEqual(
            bridged_terms("索引陈旧检测"),
            ["index", "stale", "detect"],
        )

    def test_ascii_only_text_bridges_nothing(self) -> None:
        self.assertEqual(bridged_terms("load_index staleness_reason"), [])

    def test_terms_are_deduplicated_in_first_seen_order(self) -> None:
        # 索引 and 检索 both map to English, and overlapping keys must not repeat.
        self.assertEqual(bridged_terms("索引与检索"), ["index", "search", "retrieval"])

    def test_only_whole_phrases_trigger_the_bridge(self) -> None:
        # A single overlapping character is not a phrase match.
        self.assertEqual(bridged_terms("引"), [])


class ContentPatternTests(unittest.TestCase):
    """One compiled scan per line replaces a Python loop over every term."""

    def test_no_terms_yields_no_pattern(self) -> None:
        self.assertIsNone(content_pattern([]))
        self.assertIsNone(content_pattern([""]))

    def test_terms_are_matched_literally(self) -> None:
        pattern = content_pattern(["a.b"])
        self.assertIsNotNone(pattern)
        self.assertIsNotNone(pattern.search("value a.b here"))
        self.assertIsNone(pattern.search("value axb here"))

    def test_any_term_matches(self) -> None:
        pattern = content_pattern(["token", "索引"])
        self.assertIsNotNone(pattern.search("validate_token"))
        self.assertIsNotNone(pattern.search("重建索引之后"))
        self.assertIsNone(pattern.search("nothing relevant"))


class IdentifierPartsTests(unittest.TestCase):
    """The haystack side of matching: how an indexed symbol name is read."""

    def test_snake_case_and_camel_case_are_split_into_words(self) -> None:
        self.assertEqual(identifier_parts("load_index"), {"load", "index", "load_index"})
        self.assertEqual(
            identifier_parts("TokenValidator"), {"token", "validator", "tokenvalidator"}
        )
        self.assertEqual(
            identifier_parts("INDEX_VERSION"), {"index", "version", "index_version"}
        )

    def test_a_word_inside_a_longer_word_is_not_a_match(self) -> None:
        # Substring matching made "json" hit "_write_jsonl".
        self.assertNotIn("json", identifier_parts("_write_jsonl"))
        self.assertIn("jsonl", identifier_parts("_write_jsonl"))

    def test_the_whole_name_stays_available_for_exact_matching(self) -> None:
        # A prompt that spells the identifier out must still match it exactly.
        self.assertIn("file_state", identifier_parts("file_state"))
        self.assertIn("mcp", identifier_parts("McpSurfaceTests"))


if __name__ == "__main__":
    unittest.main()
