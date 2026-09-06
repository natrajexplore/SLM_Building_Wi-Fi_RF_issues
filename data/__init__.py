"""Phase 4 — synthetic RCA dataset generation.

The pipeline is deliberately split so that *structure* is ground truth by
construction and the teacher model only supplies *language*:

    taxonomy_loader  load + index taxonomy/rf_root_causes.yaml, resolve thresholds
    predicates       evaluate the v0.2.0 required_evidence predicate grammar
    snapshots        healthy baselines + typed path read/write + satisfy/violate
    scenarios        per-cause build recipes: positive / ambiguous / abstention
    prompts          diagnosis (low-temp) and explanation (high-temp) prompts
    teacher          Ollama client, with an offline templated fallback
    generate         orchestrator + hard validation + train/eval jsonl writer

Because `snapshots`/`scenarios` build each snapshot by explicitly satisfying a
cause's `required_evidence` predicates, the generator always knows exactly
which field paths carry the evidence. Evidence grounding is therefore
guaranteed for the structural part of every label; the teacher is only ever
asked to write the `why_it_matters` prose and to phrase remediation from
`remediation_intent`. Run with `--no-teacher` and that prose comes from
templates instead — the dataset is still schema- and contract-valid.
"""
