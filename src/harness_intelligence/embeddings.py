"""Optional semantic backends for re-ranking retrieved fragments.

The shipped retriever is lexical and dependency-light by contract (see
``docs/overview.md`` §3). This module adds the *optional* semantic re-ranking
step that ``docs/roadmap.md`` §6 ties to a measurable trigger: a multilingual
embedding backend re-orders the lexically selected candidates by cosine
similarity to the task, which is the only lever left for the residual gap the
lexical scorer cannot close (a Chinese question against an English
implementation shares no surface form).

Three rules keep the core honest:

* Nothing here is imported or contacted unless embedding mode is explicitly
  requested, and nothing is required: the default is ``off``. Every failure -
  missing package, unreachable endpoint, malformed response - returns ``None``
  so retrieval degrades to the local lexical scorer instead of failing a call.
* The backend does not get to claim anything. ``benchmarks/evidence.py`` reports
  whether the Phase 4 trigger has fired, and ``benchmarks/measure.py`` is the
  only place allowed to put a recall number on the result.
* The bundled ``hash`` backend is deterministic and dependency-free on purpose.
  It exercises the re-ranking path in tests and offline; it is *not* a semantic
  model, and must not be presented as one.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from .terms import extract_terms

#: Embedding mode: ``off`` (default), ``auto``, ``on``, or a backend name.
MODE_ENV = "HIL_EMBEDDINGS"
#: Backend name for an explicit choice, overriding the ``auto`` probe order.
PROVIDER_ENV = "HIL_EMBEDDING_PROVIDER"
#: OpenAI-compatible ``POST {url}/embeddings`` base URL for the ``http`` backend.
URL_ENV = "HIL_EMBEDDING_URL"
#: Model name, shared by the ``sentence-transformers`` and ``http`` backends.
MODEL_ENV = "HIL_EMBEDDING_MODEL"
#: Optional bearer token for the ``http`` backend.
API_KEY_ENV = "HIL_EMBEDDING_API_KEY"

#: A multilingual model is the point: a monolingual one cannot bridge a Chinese
#: question to an English implementation, which is the gap this backend exists
#: for. Only a default; env overrides it.
DEFAULT_MODEL = "intfloat/multilingual-e5-small"

#: Candidate text is truncated before embedding. A fragment is usually far longer
#: than the model's useful window, and on CPU the cost is linear in tokens, so the
#: truncation mostly removes cost rather than signal (measured in docs/roadmap.md §12).
EMBED_TEXT_LIMIT = 512

OFF_MODES = {"", "off", "none", "lexical", "false", "0"}
KNOWN_BACKENDS = ("sentence-transformers", "http", "hash")


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Minimal contract every backend satisfies."""

    name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one fixed-length vector per input text."""


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, clamped to ``[-1, 1]`` and safe on zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


class HashBackend:
    """Deterministic hashed bag of terms. Offline plumbing, not semantics."""

    name = "hash"

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for term in extract_terms(text, limit=None):
            digest = hashlib.sha1(term.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            vector[index] += 1.0
        return vector

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]


class CachingBackend:
    """Wrap a backend with a disk cache keyed by the embedded text.

    CPU inference is the whole latency of semantic re-ranking (roadmap §12): each
    fragment costs ~100 ms, so a query that embeds 40 of them takes ~4 s. Candidate
    windows repeat across queries and across runs, so caching each distinct text
    once turns most of that into a hash lookup. Text is truncated first
    (``EMBED_TEXT_LIMIT``) so the key matches exactly what was embedded.
    """

    def __init__(self, backend, cache_dir: str | Path, limit: int = EMBED_TEXT_LIMIT):
        self.backend = backend
        self.name = f"{getattr(backend, 'name', 'backend')}+cache"
        self.cache_dir = Path(cache_dir)
        self.limit = limit
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / f"{getattr(backend, 'name', 'backend')}.json"
        self.store: dict[str, list[float]] = self._load()

    def _load(self) -> dict[str, list[float]]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self) -> None:
        try:
            self.cache_path.write_text(json.dumps(self.store), encoding="utf-8")
        except OSError:
            pass

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        prepared = [text[: self.limit] for text in texts]
        keys = [hashlib.sha1(text.encode("utf-8")).hexdigest() for text in prepared]
        missing = [index for index, key in enumerate(keys) if key not in self.store]
        if missing:
            vectors = self.backend.embed([prepared[index] for index in missing])
            for index, vector in zip(missing, vectors):
                self.store[keys[index]] = list(vector)
            self._save()
        return [self.store[key] for key in keys]


class SentenceTransformerBackend:
    """Local multilingual model, loaded lazily so the core stays import-free."""

    name = "sentence-transformers"

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._load().encode(list(texts), normalize_embeddings=True)
        return [list(map(float, vector)) for vector in vectors]


class HttpBackend:
    """OpenAI-compatible ``/embeddings`` endpoint, using only the standard library."""

    name = "http"

    def __init__(self, url: str, model_name: str = DEFAULT_MODEL, api_key: str = "") -> None:
        self.url = url.rstrip("/")
        self.model_name = model_name
        self.api_key = api_key

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        body = json.dumps({"model": self.model_name, "input": list(texts)}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.url}/embeddings", data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 (explicit URL)
            payload = json.loads(response.read().decode("utf-8"))
        rows = payload.get("data")
        if not isinstance(rows, list) or len(rows) != len(texts):
            raise ValueError("embedding endpoint returned an unexpected payload shape")
        vectors = []
        for row in rows:
            vector = row.get("embedding") if isinstance(row, dict) else None
            if not isinstance(vector, list) or not vector:
                raise ValueError("embedding endpoint returned a row without a vector")
            vectors.append([float(value) for value in vector])
        return vectors


#: Resolution is memoised because an ``auto`` probe may import a model. The cache
#: is keyed by the full resolved configuration, so changing an env var in a test
#: yields a fresh decision instead of a stale backend.
_BACKEND_CACHE: dict[tuple[str, ...], tuple[object | None, str]] = {}


def reset_cache() -> None:
    """Drop memoised backend decisions (used by tests that mutate the env)."""
    _BACKEND_CACHE.clear()


def _build(provider: str, model_name: str, url: str, api_key: str):
    if provider == "hash":
        return HashBackend()
    if provider == "sentence-transformers":
        return SentenceTransformerBackend(model_name)
    if provider == "http":
        if not url:
            raise ValueError(f"{URL_ENV} is required for the http backend")
        return HttpBackend(url, model_name, api_key)
    raise ValueError(f"unknown embedding backend {provider!r}")


def resolve_backend(mode: str | None = None) -> tuple[object | None, str]:
    """Return ``(backend, reason)``; ``backend`` is ``None`` for lexical-only.

    ``mode`` is an explicit override for the ``HIL_EMBEDDINGS`` environment
    variable. ``auto``/``on`` probe ``sentence-transformers`` first, then an
    ``http`` endpoint *only when one is configured*, so an unconfigured machine
    never waits on the network.
    """
    requested = (mode if mode is not None else os.environ.get(MODE_ENV, "off"))
    mode_value = requested.strip().lower()
    provider_env = os.environ.get(PROVIDER_ENV, "").strip().lower()
    model_name = os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL
    url = os.environ.get(URL_ENV, "").strip()
    api_key = os.environ.get(API_KEY_ENV, "").strip()

    if mode_value in OFF_MODES:
        return None, "embeddings off; lexical retrieval only"

    if provider_env:
        order = [provider_env]
    elif mode_value in {"auto", "on"}:
        order = ["sentence-transformers"] + (["http"] if url else [])
    elif mode_value in KNOWN_BACKENDS:
        order = [mode_value]
    else:
        return None, f"unknown embedding mode {requested!r}; lexical retrieval only"

    key = (mode_value, provider_env, model_name, url, api_key)
    cached = _BACKEND_CACHE.get(key)
    if cached is not None:
        return cached

    failures: list[str] = []
    for provider in order:
        try:
            backend = _build(provider, model_name, url, api_key)
            # A backend that cannot be constructed is not enough: sentence-
            # transformers imports lazily, so prove it here once. The probe also
            # warms the model, which keeps per-query latency predictable.
            backend.embed(["probe"])  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - any failure must degrade, not raise
            failures.append(f"{provider}: {exc.__class__.__name__}: {exc}")
            continue
        reason = f"{provider} backend ({model_name})"
        _BACKEND_CACHE[key] = (backend, reason)
        return backend, reason

    reason = "no embedding backend available (" + "; ".join(failures) + ")"
    _BACKEND_CACHE[key] = (None, reason)
    return None, reason


def describe() -> dict:
    """Report the configured mode without loading anything (for diagnostics)."""
    requested = os.environ.get(MODE_ENV, "off")
    return {
        "mode": requested,
        "provider": os.environ.get(PROVIDER_ENV, ""),
        "model": os.environ.get(MODEL_ENV, "") or DEFAULT_MODEL,
        "url_configured": bool(os.environ.get(URL_ENV, "").strip()),
    }
