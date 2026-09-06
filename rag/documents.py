"""Corpus file format + chunking.

A corpus document is a markdown file with a YAML frontmatter block:

    ---
    id: 6ghz-power-classes
    title: "6 GHz power classes — LPI, Standard Power, VLP"
    bands: [6GHz]
    domains: [US, ETSI]          # or [global]
    topics: [power]
    sources:
      - "47 CFR §15.407"
      - "FCC 20-51 (6 GHz Report and Order)"
    review_status: unverified     # curator flips to 'verified'
    ---

    ## Low Power Indoor (LPI)
    ...prose...

    ## Standard Power (SP)
    ...prose...

Chunking is by `## ` heading: each chunk is one heading plus its body, and
carries the parent doc's frontmatter. A doc with no headings is a single chunk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"

_FRONTMATTER = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
_HEADING = re.compile(r"^##\s+(.*)$", re.MULTILINE)

_REQUIRED_KEYS = ("id", "title", "bands", "domains", "topics", "sources", "review_status")
_VALID_BANDS = {"2.4GHz", "5GHz", "6GHz", "global"}
_VALID_REVIEW = {"unverified", "verified"}


class CorpusError(RuntimeError):
    """A corpus file is missing frontmatter or a required key."""


@dataclass(frozen=True)
class CorpusDoc:
    id: str
    title: str
    bands: list[str]
    domains: list[str]
    topics: list[str]
    sources: list[str]
    review_status: str
    body: str
    path: Path

    @classmethod
    def from_file(cls, path: Path) -> "CorpusDoc":
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER.match(text)
        if not m:
            raise CorpusError(f"{path.name}: no `---` frontmatter block")
        meta = yaml.safe_load(m.group(1)) or {}
        missing = [k for k in _REQUIRED_KEYS if k not in meta]
        if missing:
            raise CorpusError(f"{path.name}: frontmatter missing {', '.join(missing)}")
        if meta["review_status"] not in _VALID_REVIEW:
            raise CorpusError(f"{path.name}: review_status must be one of {_VALID_REVIEW}")
        bad_bands = set(meta["bands"]) - _VALID_BANDS
        if bad_bands:
            raise CorpusError(f"{path.name}: unknown band(s) {bad_bands}")
        return cls(
            id=str(meta["id"]),
            title=str(meta["title"]),
            bands=list(meta["bands"]),
            domains=list(meta["domains"]),
            topics=list(meta["topics"]),
            sources=list(meta["sources"]),
            review_status=str(meta["review_status"]),
            body=m.group(2).strip(),
            path=path,
        )


@dataclass(frozen=True)
class Chunk:
    doc_id: str
    title: str
    heading: str | None
    text: str
    bands: tuple[str, ...]
    domains: tuple[str, ...]
    topics: tuple[str, ...]
    sources: tuple[str, ...]
    review_status: str

    @property
    def embed_text(self) -> str:
        """What actually gets embedded — title + heading + body, so a query
        that names the topic ('6 GHz LPI EIRP limit') lands near the chunk even
        when the body phrases it differently."""
        head = f"{self.title}" + (f" — {self.heading}" if self.heading else "")
        return f"{head}\n{self.text}"

    def as_metadata(self) -> dict:
        return {
            "doc_id": self.doc_id, "title": self.title, "heading": self.heading,
            "text": self.text, "bands": list(self.bands), "domains": list(self.domains),
            "topics": list(self.topics), "sources": list(self.sources),
            "review_status": self.review_status,
        }

    @classmethod
    def from_metadata(cls, d: dict) -> "Chunk":
        return cls(
            doc_id=d["doc_id"], title=d["title"], heading=d.get("heading"),
            text=d["text"], bands=tuple(d["bands"]), domains=tuple(d["domains"]),
            topics=tuple(d["topics"]), sources=tuple(d["sources"]),
            review_status=d["review_status"],
        )


def chunk_doc(doc: CorpusDoc) -> list[Chunk]:
    common = dict(
        doc_id=doc.id, title=doc.title, bands=tuple(doc.bands), domains=tuple(doc.domains),
        topics=tuple(doc.topics), sources=tuple(doc.sources), review_status=doc.review_status,
    )
    headings = list(_HEADING.finditer(doc.body))
    if not headings:
        return [Chunk(heading=None, text=doc.body, **common)] if doc.body else []

    chunks: list[Chunk] = []
    preamble = doc.body[: headings[0].start()].strip()
    if preamble:
        chunks.append(Chunk(heading=None, text=preamble, **common))
    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(doc.body)
        section = doc.body[h.end():end].strip()
        if section:
            chunks.append(Chunk(heading=h.group(1).strip(), text=section, **common))
    return chunks


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[CorpusDoc]:
    # Files whose name starts with "_" are notes for humans (e.g. _README.md),
    # not corpus documents.
    files = sorted(p for p in corpus_dir.glob("*.md") if not p.name.startswith("_"))
    if not files:
        raise CorpusError(f"no *.md corpus files under {corpus_dir}")
    docs = [CorpusDoc.from_file(p) for p in files]
    seen: set[str] = set()
    for d in docs:
        if d.id in seen:
            raise CorpusError(f"duplicate corpus doc id: {d.id}")
        seen.add(d.id)
    return docs


def load_chunks(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in load_corpus(corpus_dir):
        out.extend(chunk_doc(doc))
    return out
