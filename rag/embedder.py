"""Text -> vector, for both ingest and query time.

`OllamaEmbedder` (default) calls a local embedding model over Ollama's HTTP
API — no Python ML dependency. `HashEmbedder` is a dependency-free, deterministic
fallback (hashed token n-grams) so the pipeline and its tests run with no Ollama
at all; its retrieval quality is poor and it is not for real use.

The ingest manifest records which embedder + model built an index; the
retriever refuses a query embedder that does not match.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request

import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+")


class EmbedderUnavailable(RuntimeError):
    """The embedding backend could not be reached."""


def _normalise(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    norm = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.clip(norm, 1e-9, None)


class OllamaEmbedder:
    name = "ollama"

    def __init__(
        self,
        model: str = os.environ.get("RF_SLM_EMBED_MODEL", "nomic-embed-text"),
        host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    @property
    def key(self) -> str:
        return f"{self.name}:{self.model}"

    def embed(self, texts: list[str]) -> np.ndarray:
        out = []
        for text in texts:
            body = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.host}/api/embeddings", data=body,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read())
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                raise EmbedderUnavailable(
                    f"Ollama embeddings at {self.host} (model {self.model!r}): {exc}"
                ) from exc
            vec = payload.get("embedding")
            if not vec:
                raise EmbedderUnavailable(f"empty embedding from {self.model!r}")
            out.append(vec)
        return _normalise(np.array(out, dtype=np.float32))

    def health_check(self) -> None:
        self.embed(["ping"])


class HashEmbedder:
    """Deterministic, offline, low-quality. Tests and `--offline` only."""

    name = "hash"

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    @property
    def key(self) -> str:
        return f"{self.name}:{self.dim}"

    def embed(self, texts: list[str]) -> np.ndarray:
        rows = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, text in enumerate(texts):
            toks = _TOKEN.findall(text.lower())
            for i in range(len(toks)):
                for gram in (toks[i], " ".join(toks[i : i + 2])):
                    h = int(hashlib.blake2b(gram.encode(), digest_size=8).hexdigest(), 16)
                    rows[r, h % self.dim] += 1.0
        return _normalise(rows)

    def health_check(self) -> None:  # always fine
        return


def get_embedder(kind: str) -> OllamaEmbedder | HashEmbedder:
    if kind in ("ollama", "nomic-embed-text"):
        return OllamaEmbedder()
    if kind in ("hash", "offline"):
        return HashEmbedder()
    raise ValueError(f"unknown embedder {kind!r}")
