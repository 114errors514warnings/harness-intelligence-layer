"""Tests for the optional semantic backend and its lexical fallback.

The contract these pin is not "embeddings improve recall" - that number may only
come from ``benchmarks/measure.py``. It is that the optional path is *optional*:
absent packages, bad configuration and mid-query failures all degrade to the
lexical scorer instead of breaking a retrieval call, and that a working backend
provably changes the ordering it is given.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harness_intelligence import embeddings, retrieval
from harness_intelligence.embeddings import HashBackend, cosine, resolve_backend
from harness_intelligence.indexer import index_project
from harness_intelligence.retrieval import Candidate, _rerank, get_project_context


class HelperBackend:
    """Deterministic backend that gives each text a chosen vector."""

    name = "helper"

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors

    def embed(self, texts):
        return [self.vectors[text] for text in texts]


class RaisingBackend:
    name = "raise"

    def embed(self, texts):
        raise RuntimeError("backend exploded")


class HashBackendTests(unittest.TestCase):
    def test_vectors_are_stable_and_fixed_length(self) -> None:
        backend = HashBackend(dimensions=32)
        first = backend.embed(["load_index staleness", "load_index staleness"])
        self.assertEqual(len(first[0]), 32)
        self.assertEqual(first[0], first[1])

    def test_different_text_produces_a_different_vector(self) -> None:
        backend = HashBackend(dimensions=64)
        left, right = backend.embed(["index rebuild", "authentication token"])
        self.assertNotEqual(left, right)

    def test_cosine_handles_zero_and_mismatched_vectors(self) -> None:
        self.assertEqual(cosine([0.0, 0.0], [1.0, 1.0]), 0.0)
        self.assertEqual(cosine([1.0, 2.0], [1.0]), 0.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)


class ResolveBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: __import__("os").environ.pop(key, None)
            for key in (
                embeddings.MODE_ENV,
                embeddings.PROVIDER_ENV,
                embeddings.URL_ENV,
                embeddings.MODEL_ENV,
            )
        }
        embeddings.reset_cache()

    def tearDown(self) -> None:
        import os

        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value
        embeddings.reset_cache()

    def test_default_is_off_and_uses_no_backend(self) -> None:
        backend, reason = resolve_backend()
        self.assertIsNone(backend)
        self.assertIn("off", reason)

    def test_unknown_mode_degrades_instead_of_raising(self) -> None:
        backend, reason = resolve_backend("nonsense")
        self.assertIsNone(backend)
        self.assertIn("unknown embedding mode", reason)

    def test_http_without_a_url_degrades(self) -> None:
        backend, reason = resolve_backend("http")
        self.assertIsNone(backend)
        self.assertIn("HIL_EMBEDDING_URL", reason)

    def test_auto_without_dependencies_degrades_to_lexical(self) -> None:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            backend, reason = resolve_backend("auto")
            self.assertIsNone(backend)
            self.assertIn("no embedding backend available", reason)
        else:  # pragma: no cover - exercised only where a model is installed
            backend, reason = resolve_backend("auto")
            self.assertIsNotNone(backend)

    def test_hash_mode_is_available_offline(self) -> None:
        backend, reason = resolve_backend("hash")
        self.assertIsInstance(backend, HashBackend)
        self.assertIn("hash", reason)


class RerankTests(unittest.TestCase):
    def _candidates(self) -> list[Candidate]:
        return [
            Candidate("a.py", 1, 1, "alpha", 10.0, []),
            Candidate("b.py", 1, 1, "beta", 8.0, []),
            Candidate("c.py", 1, 1, "gamma", 6.0, []),
        ]

    def test_backend_similarity_reorders_the_shortlist(self) -> None:
        # Lexical order is a, b, c. The task vector points hardest at gamma, so
        # re-ranking must move it up instead of echoing the lexical order.
        backend = HelperBackend(
            {
                "task": [1.0, 0.0],
                "alpha": [0.0, 1.0],
                "beta": [0.5, 0.5],
                "gamma": [1.0, 0.0],
            }
        )
        candidates = self._candidates()
        reranked = _rerank(candidates, "task", backend)
        self.assertEqual(reranked, 3)
        self.assertEqual(candidates[0].path, "c.py")
        self.assertTrue(any(reason.startswith("embedding:") for reason in candidates[0].reasons))

    def test_a_single_candidate_is_left_alone(self) -> None:
        candidates = [Candidate("a.py", 1, 1, "alpha", 1.0, [])]
        self.assertEqual(_rerank(candidates, "task", HelperBackend({})), 0)
        self.assertEqual(candidates[0].path, "a.py")


class RetrievalIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "indexer.py").write_text(
            "def load_index(root):\n    return root\n", encoding="utf-8"
        )
        # A second file keeps the candidate pool above the re-rank minimum of
        # two; a single candidate must never trigger (or be able to test) the
        # re-ranking path.
        (self.root / "src" / "store.py").write_text(
            "from indexer import load_index\n\n\ndef refresh(root):\n    return load_index(root)\n",
            encoding="utf-8",
        )
        index_project(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_off_keeps_pure_lexical_retrieval(self) -> None:
        result = get_project_context("load_index", self.root, 600, embedding="off")
        self.assertEqual(result["retrieval"]["mode"], "lexical")
        self.assertIsNone(result["retrieval"]["backend"])

    def test_hash_backend_is_reported_as_active(self) -> None:
        result = get_project_context("load_index", self.root, 600, embedding="hash")
        self.assertEqual(result["retrieval"]["mode"], "embedding")
        self.assertEqual(result["retrieval"]["backend"], "hash")
        self.assertGreaterEqual(result["retrieval"]["reranked"], 1)

    def test_a_backend_failure_degrades_to_lexical(self) -> None:
        original = retrieval.resolve_backend
        retrieval.resolve_backend = lambda mode=None: (RaisingBackend(), "forced")
        try:
            result = get_project_context("load_index", self.root, 600)
        finally:
            retrieval.resolve_backend = original
        self.assertEqual(result["retrieval"]["mode"], "lexical")
        self.assertIn("re-rank failed", result["retrieval"]["detail"])


class FallbackSignalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("def run():\n    pass\n", encoding="utf-8")
        index_project(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_an_empty_package_asks_the_harness_to_fall_back(self) -> None:
        result = get_project_context("zzzz-nothing-matches-zzzz", self.root, 600)
        self.assertFalse(result["sufficient"])
        self.assertIsNotNone(result["fallback"])
        self.assertIn("WARNING", result["notice"])

    def test_a_matched_query_is_marked_sufficient(self) -> None:
        result = get_project_context("run", self.root, 600)
        self.assertTrue(result["sufficient"])
        self.assertIsNone(result["fallback"])


if __name__ == "__main__":
    unittest.main()
