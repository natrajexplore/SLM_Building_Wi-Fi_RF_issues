"""Phase 5 — QLoRA fine-tune of the student base on the phase-4 synthetic set.

Not runnable on this machine yet (no GPU arranged — see CLAUDE.md). The scaffold
is complete and dependency-guarded:

    qlora_config.yaml       base model, LoRA + 4-bit params, optimiser schedule
                            (defaults tuned for a 16 GB card / Colab T4)
    qlora_config.8gb.yaml   low-VRAM preset for an 8 GB card — batch 1, seq 1536,
                            LoRA r=8; same effective batch, ~6-7 GB peak
    train.py            SFT loop (transformers + peft + trl); `--dry-run` needs
                        no GPU and no heavy deps — it validates the config and
                        the dataset and prints the first formatted example
    evaluate.py         the CLAUDE.md evaluation targets as pure, importable
                        scoring functions, plus responders for Ollama / a local
                        adapter so the same metrics run against any model

Heavy dependencies live in requirements-train.txt, deliberately separate from
the core requirements.txt.
"""
