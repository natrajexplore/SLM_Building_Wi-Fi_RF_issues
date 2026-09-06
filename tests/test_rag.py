"""Tests for the phase-6 retrieval layer (rag/).

All offline: the HashEmbedder needs no Ollama. Retrieval quality with it is
poor by design — these tests check plumbing, filtering, citation shape and
ranking direction, not embedding quality.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from rag import ingest
from rag.documents import CorpusDoc, CorpusError, chunk_doc, load_corpus
from rag.embedder import HashEmbedder
from rag.retriever import Retriever, RetrieverError

_DOC_A = """\
---
id: doc-a
title: "2.4 GHz channel plan"
bands: [2.4GHz]
domains: [global]
topics: [channel_plan]
sources: ["IEEE 802.11-2020 Annex E"]
review_status: unverified
---
## Non-overlapping channels
Channels 1, 6 and 11 are the only non-overlapping set in the 2.4 GHz band.

## Wide channels
40 MHz operation in 2.4 GHz consumes two of the three non-overlapping channels.
"""

_DOC_B = """\
---
id: doc-b
title: "6 GHz power classes"
bands: [6GHz]
domains: [US]
topics: [power]
sources: ["47 CFR 15.407"]
review_status: verified
---
Standard Power operation in 6 GHz requires a valid AFC grant. Without a grant
the access point falls back to Low Power Indoor limits.
"""


def _write_corpus(d: Path) -> None:
    (d / "a.md").write_text(_DOC_A, encoding="utf-8")
    (d / "b.md").write_text(_DOC_B, encoding="utf-8")
    (d / "_notes.md").write_text("just a note, no frontmatter", encoding="utf-8")


class DocumentTests(unittest.TestCase):
    def test_shipped_corpus_all_parses(self):
        docs = load_corpus()  # rag/corpus/*.md
        self.assertGreaterEqual(len(docs), 5)
        for doc in docs:
            self.assertTrue(doc.sources)
            self.assertIn(doc.review_status, {"unverified", "verified"})
            for b in doc.bands:
                self.assertIn(b, {"2.4GHz", "5GHz", "6GHz", "global"})

    def test_underscore_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            _write_corpus(Path(d))
            ids = {doc.id for doc in load_corpus(Path(d))}
            self.assertEqual(ids, {"doc-a", "doc-b"})

    def test_chunking_splits_on_headings_and_carries_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.md").write_text(_DOC_A, encoding="utf-8")
            doc = load_corpus(Path(d))[0]
            chunks = chunk_doc(doc)
        self.assertEqual([c.heading for c in chunks],
                         ["Non-overlapping channels", "Wide channels"])
        self.assertTrue(all(c.topics == ("channel_plan",) for c in chunks))
        self.assertIn("1, 6 and 11", chunks[0].text)

    def test_missing_frontmatter_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.md"
            p.write_text("no frontmatter here", encoding="utf-8")
            with self.assertRaises(CorpusError):
                CorpusDoc.from_file(p)

    def test_missing_required_key_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bad.md"
            p.write_text("---\nid: x\ntitle: y\n---\nbody", encoding="utf-8")
            with self.assertRaises(CorpusError):
                CorpusDoc.from_file(p)


class EmbedderTests(unittest.TestCase):
    def test_hash_embedder_is_deterministic_and_normalised(self):
        e = HashEmbedder(dim=64)
        a = e.embed(["dynamic frequency selection radar"])
        b = e.embed(["dynamic frequency selection radar"])
        np.testing.assert_array_equal(a, b)
        self.assertAlmostEqual(float(np.linalg.norm(a[0])), 1.0, places=5)
        self.assertEqual(a.shape, (1, 64))


class RetrieverTests(unittest.TestCase):
    def _build(self, d: Path) -> Retriever:
        corpus, index = d / "corpus", d / "index"
        corpus.mkdir()
        _write_corpus(corpus)
        ingest.build(corpus, index, "hash")
        return Retriever.load(index, embedder=HashEmbedder())

    def test_ingest_writes_index_files_and_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            self._build(Path(d))
            idx = Path(d) / "index"
            self.assertTrue((idx / "vectors.npy").exists())
            self.assertTrue((idx / "chunks.jsonl").exists())
            m = ingest.json.loads((idx / "manifest.json").read_text())
            self.assertEqual(m["embedder"], "hash:384")
            self.assertEqual(m["review_status"], {"unverified": 2, "verified": 1})

    def test_retrieval_ranks_the_lexically_closest_chunk_first(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(Path(d))
            hits = r.retrieve("AFC grant standard power fallback low power indoor", k=3)
            self.assertTrue(hits)
            self.assertEqual(hits[0].doc_id, "doc-b")

    def test_band_filter_excludes_other_bands(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(Path(d))
            hits = r.retrieve("channels", k=5, bands=["6GHz"])
            self.assertTrue(all(h.doc_id == "doc-b" for h in hits))

    def test_topic_filter(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(Path(d))
            self.assertEqual({h.doc_id for h in r.retrieve("x", k=5, topics=["power"])}, {"doc-b"})
            self.assertFalse(r.retrieve("x", k=5, topics=["dfs"]))

    def test_citation_marks_unverified_and_lists_sources(self):
        with tempfile.TemporaryDirectory() as d:
            r = self._build(Path(d))
            a = next(h for h in r.retrieve("non-overlapping", k=5) if h.doc_id == "doc-a")
            b = next(h for h in r.retrieve("AFC", k=5) if h.doc_id == "doc-b")
        self.assertIn("[UNVERIFIED]", a.cite())
        self.assertNotIn("[UNVERIFIED]", b.cite())
        self.assertIn("IEEE 802.11-2020 Annex E", a.cite())

    def test_embedder_key_mismatch_refuses_to_load(self):
        with tempfile.TemporaryDirectory() as d:
            corpus, index = Path(d) / "corpus", Path(d) / "index"
            corpus.mkdir()
            _write_corpus(corpus)
            ingest.build(corpus, index, "hash")
            with self.assertRaises(RetrieverError):
                Retriever.load(index, embedder=HashEmbedder(dim=128))  # key hash:128 != hash:384


if __name__ == "__main__":
    unittest.main()
