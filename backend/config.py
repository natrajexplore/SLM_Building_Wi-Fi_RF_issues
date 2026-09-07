"""Backend configuration.

Hard design decision #3 (CLAUDE.md): temperature is split by stage. The
diagnosis path is pinned low HERE and the API never lets a caller raise it.
The explanation path takes a caller value, clamped to its band. There is no
single global temperature knob and there must never be one.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    # model backend
    model_backend: str = os.environ.get("RF_SLM_BACKEND", "ollama")  # ollama | adapter | reference | stub
    diagnose_model: str = os.environ.get("RF_SLM_DIAGNOSE_MODEL", "qwen2.5:7b-instruct")
    explain_model: str = os.environ.get("RF_SLM_EXPLAIN_MODEL", "qwen2.5:7b-instruct")
    ollama_host: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    # /ask (Submit/Ask tab) backend -- deliberately separate from model_backend.
    # ReferenceBackend is a deterministic rule engine that only ever emits
    # diagnosis JSON; it cannot hold a free-text conversation, so "reference"
    # is not a valid choice here even when it is the diagnose/explain backend.
    ask_backend: str = os.environ.get("RF_SLM_ASK_BACKEND", "ollama")  # ollama | adapter | stub
    ask_model: str = os.environ.get("RF_SLM_ASK_MODEL", "qwen2.5:7b-instruct")

    # adapter backend (RF_SLM_BACKEND=adapter): the phase-5 QLoRA output
    adapter_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("RF_SLM_ADAPTER_DIR", str(REPO / "training" / "out")))
    )
    adapter_base_model: str | None = os.environ.get("RF_SLM_ADAPTER_BASE") or None
    generate_max_new_tokens: int = 800

    # temperature, per stage — NOT a single global value
    diagnose_temperature: float = 0.15          # fixed; the API forbids overriding it
    explain_temperature_min: float = 0.7
    explain_temperature_max: float = 0.9
    explain_temperature_default: float = 0.8

    # retrieval
    rag_enabled: bool = os.environ.get("RF_SLM_RAG", "1") != "0"
    rag_index_dir: Path = field(default_factory=lambda: REPO / "rag" / "index")
    rag_top_k: int = 4

    generate_timeout: float = 240.0

    def clamp_explain_temperature(self, value: float | None) -> float:
        if value is None:
            return self.explain_temperature_default
        return max(self.explain_temperature_min, min(self.explain_temperature_max, value))


_SETTINGS = Settings()


def get_settings() -> Settings:
    return _SETTINGS
