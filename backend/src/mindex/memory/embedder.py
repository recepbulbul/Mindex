"""Text embedders for the persistent memory (P5).

`Embedder` is the seam, like `ChatClient` in `mindex.agents.llm`: production uses
`LlamaServerEmbedder` (Qwen3-Embedding behind llama-server's OpenAI-compatible
`/embeddings`), tests and development use the deterministic `HashEmbedder`.
"""

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol, cast

import httpx2

from mindex.db.models import EMBEDDING_DIM

TOKEN_RE = re.compile(r"\w+")


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """One `EMBEDDING_DIM`-long vector per text, in input order."""
        ...


class EmbeddingUnavailableError(RuntimeError):
    pass


def tokenize(text: str) -> list[str]:
    # "İ".lower() is "i" + a combining dot that `\w` splits on; PostgreSQL folds it to "i".
    return TOKEN_RE.findall(text.replace("İ", "i").lower())


class HashEmbedder:
    """Deterministic bag-of-words embedder (feature hashing), no model needed.

    Every token is hashed (`hashlib`, not the per-process salted `hash()`) to a few signed
    coordinates; the sum is L2-normalised. Texts sharing tokens get a high cosine similarity,
    so retrieval tests are meaningful. A text without tokens maps to a fixed unit vector
    instead of the zero vector, whose cosine distance would be NaN.
    """

    def __init__(self, dim: int = EMBEDDING_DIM, *, hashes_per_token: int = 4) -> None:
        self.dim = dim
        self.hashes_per_token = hashes_per_token

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode()).digest()
            for i in range(self.hashes_per_token):
                chunk = int.from_bytes(digest[4 * i : 4 * i + 4], "big")
                vec[chunk % self.dim] += 1.0 if (chunk >> 31) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class LlamaServerEmbedder:
    """OpenAI-compatible `/embeddings` client for llama.cpp `llama-server` (Qwen3-Embedding).

    `transport` is injectable so tests can use `httpx2.MockTransport`.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 30.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an http(s) URL")
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model = model
        self.timeout = timeout
        self.transport = transport

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        body = {"model": self.model, "input": list(texts), "encoding_format": "float"}
        try:
            with httpx2.Client(transport=self.transport, timeout=self.timeout) as client:
                resp = client.post(self.url, json=body)
                resp.raise_for_status()
                payload: object = resp.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise EmbeddingUnavailableError(str(exc)) from exc
        return _parse_embeddings(payload, len(texts))


def _parse_embeddings(payload: object, expected: int) -> list[list[float]]:
    """Validate an OpenAI-style `{"data": [{"index", "embedding"}]}` response.

    Anything malformed raises `EmbeddingUnavailableError`, including non-finite values and
    the zero vector (its cosine distance is NaN, which would break the ranking).
    """
    data = cast(dict[str, Any], payload).get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise EmbeddingUnavailableError("malformed embeddings response: no `data` list")
    items = cast(list[object], data)
    if len(items) != expected:
        raise EmbeddingUnavailableError(f"expected {expected} embeddings, got {len(items)}")
    try:
        rows = [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]
        if len(rows) != expected:
            raise TypeError("embedding item is not an object")
        if sorted(_strict_index(row["index"]) for row in rows) != list(range(expected)):
            raise ValueError("indices must be 0..n-1 without repeats")
        rows.sort(key=lambda d: cast(int, d["index"]))
        vectors = [_strict_vector(row["embedding"]) for row in rows]
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise EmbeddingUnavailableError(f"malformed embeddings response: {exc}") from exc
    for vec in vectors:
        if len(vec) != EMBEDDING_DIM:
            raise EmbeddingUnavailableError(f"expected dim {EMBEDDING_DIM}, got {len(vec)}")
        if not all(math.isfinite(x) for x in vec):
            raise EmbeddingUnavailableError("embedding has non-finite values")
        if not any(vec):
            raise EmbeddingUnavailableError("embedding is the zero vector")
    return vectors


def _strict_index(value: object) -> int:
    # bool is an int subclass; numeric strings and floats are not indices either.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"index must be an integer, got {value!r}")
    return value


def _strict_vector(value: object) -> list[float]:
    if not isinstance(value, list):
        raise TypeError("embedding must be a list")
    vec: list[float] = []
    for x in cast(list[object], value):
        if isinstance(x, bool) or not isinstance(x, int | float):
            raise TypeError(f"embedding values must be numbers, got {x!r}")
        vec.append(float(x))  # OverflowError for huge integers -> ArithmeticError
    return vec
