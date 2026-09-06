"""Phase 6 — retrieval layer.

Hard design decision #4 (CLAUDE.md): RAG stays in the loop after fine-tuning.
The SLM learns the reasoning *pattern*; this layer supplies the *facts* —
regulatory tables, channel plans, power limits, IEEE clauses. A 1.5B model
must never state a numeric limit from parametric memory, so every such claim
in a diagnosis has to carry a citation returned from here.

    rag/corpus/        curated standards + regulatory docs (markdown + frontmatter)
    documents.py       parse corpus files -> CorpusDoc -> Chunk
    embedder.py        Ollama embeddings, with an offline hash fallback
    ingest.py          embed the corpus -> rag/index/
    retriever.py       query -> ranked Citations (with band/domain/topic filters)

The corpus is curator-owned. Every shipped doc is `review_status: unverified`
until the wireless architect has checked it against the primary source; the
retriever surfaces that status on every Citation so an unverified fact is never
cited as settled.
"""
