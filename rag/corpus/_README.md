# RAG corpus — standards & regulatory only

Every file here is one focused fact sheet. It feeds the retrieval layer that
supplies numeric limits (channel plans, power, DFS timing, IEEE clauses) the
1.5B student must not state from memory.

## Rules for this directory

- **Standards and regulation only.** No vendor design guides, no product docs,
  no tuning opinions. If it is not traceable to IEEE 802.11, an ITU-R
  recommendation, or a national regulator (FCC, ETSI/CEPT, MIC, ISED, ACMA …),
  it does not belong here.
- **One topic per file.** Small chunks retrieve better and cite more precisely.
- **Frontmatter is mandatory** — see any file for the shape, or
  `rag/documents.py` for the schema. `id`, `title`, `bands`, `domains`,
  `topics`, `sources`, `review_status`.
- **`review_status: unverified` is the default.** The wireless architect flips a
  file to `verified` only after checking it line-by-line against the cited
  primary source. The retriever marks every unverified citation `[UNVERIFIED]`.
- **Regional values differ.** When a limit is US-specific, set `domains: [US]`
  and say so in the text; do not imply it is global.

## Files shipped as a starting point

These were drafted to get the pipeline working end-to-end and to cover what
`taxonomy/rf_root_causes.yaml` references. All 10 starter files have since
been checked against their cited sources and flipped to `verified` — three
(`5ghz-dfs.md`, `6ghz-power-classes.md`, `eirp-limits-24-5ghz.md`) had real
numeric errors corrected in the process. Any new file added here still starts
`unverified` until checked the same way.

Rebuild the index after any change: `python -m rag.ingest`
