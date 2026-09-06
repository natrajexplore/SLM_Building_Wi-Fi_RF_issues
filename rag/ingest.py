"""Build the retrieval index from rag/corpus/.

    python -m rag.ingest                          # Ollama embeddings -> rag/index/
    python -m rag.ingest --embedder hash          # offline, for testing only

Output (rag/index/):
    vectors.npy     float32 [n_chunks, dim], L2-normalised
    chunks.jsonl    one chunk's metadata + text per line, row-aligned to vectors
    manifest.json   embedder key, dim, counts, build time, review-status summary

The on-disk format is deliberately plain numpy; FAISS, if installed, is used
only as an in-memory search accelerator by the retriever (identical results
for exact search).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from rag.documents import CORPUS_DIR, load_chunks
from rag.embedder import EmbedderUnavailable, get_embedder

INDEX_DIR = Path(__file__).resolve().parent / "index"


def build(corpus_dir: Path, out_dir: Path, embedder_kind: str) -> dict:
    chunks = load_chunks(corpus_dir)
    if not chunks:
        raise SystemExit(f"no chunks produced from {corpus_dir}")

    embedder = get_embedder(embedder_kind)
    try:
        embedder.health_check()
    except EmbedderUnavailable as exc:
        raise SystemExit(
            f"embedder unavailable: {exc}\n  try --embedder hash for an offline index."
        )

    vectors = embedder.embed([c.embed_text for c in chunks])

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_dir / "vectors.npy", vectors)
    with open(out_dir / "chunks.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.as_metadata()) + "\n")

    review = Counter(c.review_status for c in chunks)
    manifest = {
        "embedder": embedder.key,
        "dim": int(vectors.shape[1]),
        "n_chunks": len(chunks),
        "n_docs": len({c.doc_id for c in chunks}),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "review_status": dict(review),
        "corpus_dir": str(corpus_dir),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", type=Path, default=CORPUS_DIR)
    ap.add_argument("--out", type=Path, default=INDEX_DIR)
    ap.add_argument("--embedder", default="ollama", choices=["ollama", "hash"])
    args = ap.parse_args(argv)

    manifest = build(args.corpus, args.out, args.embedder)
    print(json.dumps(manifest, indent=2))
    if manifest["review_status"].get("unverified"):
        print(
            f"\nNOTE: {manifest['review_status']['unverified']} of {manifest['n_chunks']} "
            "chunks are review_status=unverified — a curator must check them against "
            "the primary sources before these facts are cited as settled.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
