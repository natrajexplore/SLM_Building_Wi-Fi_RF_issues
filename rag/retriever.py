"""Query the index -> ranked Citations.

    from rag.retriever import Retriever
    r = Retriever.load()
    for c in r.retrieve("6 GHz LPI EIRP limit", bands=["6GHz"], domains=["US"]):
        print(c.cite())

    python -m rag.retriever "DFS channel availability check duration" --band 5GHz

Every Citation carries its `sources` and `review_status`, so the caller (the
diagnosis path, the hallucination checker) can require a citation for any numeric
regulatory claim and can flag one that rests on an unverified chunk.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rag.documents import Chunk
from rag.embedder import OllamaEmbedder, get_embedder
from rag.ingest import INDEX_DIR

try:  # optional in-memory search accelerator
    import faiss  # type: ignore

    _HAVE_FAISS = True
except ImportError:  # pragma: no cover
    _HAVE_FAISS = False


@dataclass(frozen=True)
class Citation:
    text: str
    doc_id: str
    title: str
    heading: str | None
    sources: tuple[str, ...]
    bands: tuple[str, ...]
    domains: tuple[str, ...]
    topics: tuple[str, ...]
    review_status: str
    score: float

    def cite(self) -> str:
        where = f"{self.title}" + (f" § {self.heading}" if self.heading else "")
        src = "; ".join(self.sources) if self.sources else "no source listed"
        flag = "" if self.review_status == "verified" else " [UNVERIFIED]"
        return f"{where} ({src}){flag}"


class RetrieverError(RuntimeError):
    pass


class Retriever:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray, manifest: dict, embedder) -> None:
        self.chunks = chunks
        self.vectors = vectors.astype(np.float32)
        self.manifest = manifest
        self.embedder = embedder
        self._faiss = None
        if _HAVE_FAISS and len(chunks):
            idx = faiss.IndexFlatIP(self.vectors.shape[1])
            idx.add(self.vectors)
            self._faiss = idx

    @classmethod
    def load(cls, index_dir: Path = INDEX_DIR, embedder=None) -> "Retriever":
        if not (index_dir / "manifest.json").exists():
            raise RetrieverError(
                f"no index at {index_dir} — run: python -m rag.ingest"
            )
        manifest = json.loads((index_dir / "manifest.json").read_text())
        vectors = np.load(index_dir / "vectors.npy")
        chunks = [
            Chunk.from_metadata(json.loads(line))
            for line in (index_dir / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(chunks) != len(vectors):
            raise RetrieverError("chunks.jsonl and vectors.npy are not the same length")

        embedder = embedder or get_embedder(manifest["embedder"].split(":", 1)[0])
        if embedder.key != manifest["embedder"]:
            raise RetrieverError(
                f"index was built with {manifest['embedder']!r} but the query embedder "
                f"is {embedder.key!r} — vectors are not comparable. Re-ingest or match."
            )
        return cls(chunks, vectors, manifest, embedder)

    def retrieve(
        self,
        query: str,
        k: int = 4,
        *,
        bands: list[str] | None = None,
        domains: list[str] | None = None,
        topics: list[str] | None = None,
        min_score: float = 0.0,
    ) -> list[Citation]:
        if not self.chunks:
            return []
        keep = self._filter_mask(bands, domains, topics)
        if not keep.any():
            return []

        qv = self.embedder.embed([query])[0].astype(np.float32)
        scores = self.vectors @ qv
        scores = np.where(keep, scores, -np.inf)
        order = np.argsort(-scores)[: max(k, 1)]

        out: list[Citation] = []
        for i in order:
            s = float(scores[i])
            if s == -np.inf or s < min_score:
                continue
            c = self.chunks[i]
            out.append(Citation(
                text=c.text, doc_id=c.doc_id, title=c.title, heading=c.heading,
                sources=c.sources, bands=c.bands, domains=c.domains, topics=c.topics,
                review_status=c.review_status, score=round(s, 4),
            ))
        return out

    def _filter_mask(self, bands, domains, topics) -> np.ndarray:
        mask = np.ones(len(self.chunks), dtype=bool)
        for i, c in enumerate(self.chunks):
            if bands and not (set(bands) & set(c.bands)) and "global" not in c.bands:
                mask[i] = False
            if domains and not (set(domains) & set(c.domains)) and "global" not in c.domains:
                mask[i] = False
            if topics and not (set(topics) & set(c.topics)):
                mask[i] = False
        return mask


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=4)
    ap.add_argument("--band", action="append", dest="bands")
    ap.add_argument("--domain", action="append", dest="domains")
    ap.add_argument("--topic", action="append", dest="topics")
    ap.add_argument("--index", type=Path, default=INDEX_DIR)
    args = ap.parse_args(argv)

    r = Retriever.load(args.index)
    hits = r.retrieve(args.query, k=args.k, bands=args.bands, domains=args.domains, topics=args.topics)
    if not hits:
        print("(no matching chunks)")
        return 0
    for c in hits:
        print(f"\n[{c.score:+.3f}] {c.cite()}")
        print("  " + c.text.replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
