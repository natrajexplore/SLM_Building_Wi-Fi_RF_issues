"""Model backends and the diagnose / explain orchestration.

`ModelBackend` is the seam: `OllamaBackend` serves now, an adapter-based backend
slots in once the QLoRA fine-tune exists (phase 5), `StubBackend` is for tests.
The orchestration around it — strip provenance, retrieve regulatory context,
call the model at the STAGE-APPROPRIATE temperature, enforce the output
contract — does not change when the backend does.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from data.prompts import ASK_SYSTEM, DIAGNOSIS_SYSTEM, EXPLANATION_SYSTEM
from data.taxonomy_loader import all_cause_ids, cause as get_cause
from training.evaluate import extract_json

from backend.config import Settings
from backend.rca import RCAContractError, validate_rca
from backend.schemas import Citation, RCAResult

try:
    from rag.retriever import Retriever
except Exception:  # pragma: no cover - rag deps missing
    Retriever = None  # type: ignore


class BackendError(RuntimeError):
    pass


class ModelBackend(Protocol):
    def generate(self, system: str, user: str, *, temperature: float) -> str: ...


class OllamaBackend:
    def __init__(self, model: str, host: str, timeout: float) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def generate(self, system: str, user: str, *, temperature: float) -> str:
        body = json.dumps({
            "model": self.model, "stream": False,
            "options": {"temperature": temperature},
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise BackendError(f"Ollama at {self.host} (model {self.model!r}): {exc}") from exc
        return (payload.get("message") or {}).get("content", "")


class StubBackend:
    """Returns queued canned responses. Tests set these; never used in serving."""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate(self, system: str, user: str, *, temperature: float) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self._responses.pop(0) if self._responses else "{}"


class ReferenceBackend:
    """Deterministic ground-truth-quality diagnoses — NOT a language model.

    Runs the same predicate/evidence logic the phase-4 dataset was built with:
    finds every assertion-eligible cause, ranks by severity, and emits a
    contract-valid RCA (or an abstention when nothing is eligible). It exists so
    the frontend and the pipeline can be exercised with realistic output before
    the phase-5 fine-tune exists — a "this is the target" reference, not the
    product. Select with RF_SLM_BACKEND=reference.
    """

    _SEV = {"high": 3, "medium": 2, "low": 1}

    def generate(self, system: str, user: str, *, temperature: float) -> str:
        from data import predicates, scenarios
        from data.taxonomy_loader import all_cause_ids, cause as get_cause

        try:
            snapshot = json.loads(user.split("\nCanonical RF snapshot:\n", 1)[1])
        except (IndexError, json.JSONDecodeError):
            return json.dumps({"cause_id": None, "confidence": "low", "evidence": [],
                               "affected_bands": [], "remediation": [], "data_gaps": []})

        band = snapshot.get("radio", {}).get("band")
        eligible = [c for c in all_cause_ids() if predicates.required_evidence_met(snapshot, get_cause(c))]
        eligible.sort(key=lambda c: self._SEV.get(get_cause(c).get("severity_default"), 0), reverse=True)

        if not eligible:
            gaps = sorted({
                p for c in all_cause_ids() if band in get_cause(c)["bands"]
                for p in predicates.evidence_paths(get_cause(c))
            })[:6]
            return json.dumps({
                "cause_id": None, "confidence": "low", "evidence": [],
                "affected_bands": [band] if band else [],
                "remediation": ["Collect the gating telemetry for the closest-matching "
                                "causes before asserting one."],
                "data_gaps": gaps,
            })

        primary, cause = eligible[0], get_cause(eligible[0])
        held = scenarios._held_evidence_paths(snapshot, cause)
        evidence = [{
            "field_path": p,
            "observed_value": scenarios._observed(snapshot, p),
            "why_it_matters": f"The observed {predicates.parse_path(p)[-1][0]} is in the "
                              f"range this cause requires.",
        } for p in held]
        out = {
            "cause_id": primary,
            "confidence": "high" if cause.get("severity_default") == "high" and len(eligible) == 1 else "medium",
            "evidence": evidence,
            "affected_bands": [band] if band else list(cause["bands"]),
            "remediation": list(cause.get("remediation_intent", [])),
            "data_gaps": scenarios._supporting_gaps(snapshot, cause),
        }
        if len(eligible) > 1:
            out["ranked_alternatives"] = [{"cause_id": c, "confidence": "low"} for c in eligible[1:3]]
        return json.dumps(out)


class AdapterBackend:
    """Base model + the phase-5 QLoRA adapter, loaded once and held in memory.

    This is the intended production backend: the student was fine-tuned to emit
    exactly the output contract, so it clears `rca.py` far more reliably than a
    generic model. Heavy deps (torch / transformers / peft) are imported here,
    not at module load, so the rest of `backend/` stays importable without them.
    """

    def __init__(self, cfg: Settings) -> None:
        adapter_dir = Path(cfg.adapter_dir)
        if not (adapter_dir / "adapter_config.json").exists():
            raise BackendError(
                f"no LoRA adapter at {adapter_dir} — run phase 5 "
                "(`python -m training.train`) or set RF_SLM_ADAPTER_DIR"
            )
        try:
            import torch
            from peft import PeftConfig, PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise BackendError(
                f"adapter backend needs the training deps ({exc}) — "
                "pip install -r requirements-train.txt"
            ) from exc

        base = cfg.adapter_base_model or PeftConfig.from_pretrained(adapter_dir).base_model_name_or_path
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(adapter_dir)
        model = AutoModelForCausalLM.from_pretrained(
            base, torch_dtype=torch.bfloat16, device_map="auto"
        )
        self.model = PeftModel.from_pretrained(model, str(adapter_dir))
        self.model.eval()
        self.max_new_tokens = cfg.generate_max_new_tokens

    def generate(self, system: str, user: str, *, temperature: float) -> str:
        inputs = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            add_generation_prompt=True,
            return_tensors="pt",
        ).to(self.model.device)
        with self._torch.no_grad():
            out = self.model.generate(
                inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=temperature > 0,
                temperature=max(temperature, 1e-3),
                pad_token_id=self.tokenizer.eos_token_id,
            )
        return self.tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)


def build_backend(cfg: Settings) -> ModelBackend:
    if cfg.model_backend == "stub":
        return StubBackend()
    if cfg.model_backend == "ollama":
        return OllamaBackend(cfg.diagnose_model, cfg.ollama_host, cfg.generate_timeout)
    if cfg.model_backend == "reference":
        return ReferenceBackend()
    if cfg.model_backend == "adapter":
        return AdapterBackend(cfg)
    raise BackendError(f"unknown model backend {cfg.model_backend!r}")


# --- retrieval enrichment ----------------------------------------------


def _retrieval_query(snapshot: dict) -> str:
    radio = snapshot.get("radio", {})
    ac = snapshot.get("analysis_context", {})
    bits = [f"{radio.get('band', '')} RF root cause"]
    if ac.get("reported_symptom"):
        bits.append(ac["reported_symptom"])
    m = snapshot.get("rf_metrics", {})
    for k in ("noise_floor_dbm", "channel_utilization_pct", "co_channel_neighbors"):
        if k in m:
            bits.append(f"{k} {m[k]}")
    if radio.get("power_mode") in ("LPI", "SP"):
        bits.append(f"6 GHz power mode {radio['power_mode']} AFC")
    return "; ".join(str(b) for b in bits if b)


def _resolve_retriever(cfg: Settings, retriever):
    if retriever is not None:
        return retriever
    if not cfg.rag_enabled or Retriever is None:
        return None
    try:
        return Retriever.load(cfg.rag_index_dir)
    except Exception:
        return None


def _citations_from_hits(hits) -> list[Citation]:
    return [
        Citation(title=h.title, heading=h.heading, sources=list(h.sources),
                 review_status=h.review_status, score=h.score, text=h.text)
        for h in hits
    ]


def retrieve_context(snapshot: dict, cfg: Settings, retriever=None) -> list[Citation]:
    if not cfg.rag_enabled:
        return []
    retriever = _resolve_retriever(cfg, retriever)
    if retriever is None:
        return []
    band = snapshot.get("radio", {}).get("band")
    hits = retriever.retrieve(
        _retrieval_query(snapshot), k=cfg.rag_top_k, bands=[band] if band else None
    )
    return _citations_from_hits(hits)


def retrieve_for_text(query: str, cfg: Settings, retriever=None) -> list[Citation]:
    """Same retrieval as retrieve_context, but for a free-text question with no
    canonical snapshot to derive a query or band filter from (used by /ask)."""
    if not cfg.rag_enabled:
        return []
    retriever = _resolve_retriever(cfg, retriever)
    if retriever is None:
        return []
    hits = retriever.retrieve(query, k=cfg.rag_top_k)
    return _citations_from_hits(hits)


def _context_block(citations: list[Citation]) -> str:
    if not citations:
        return "Retrieved regulatory context: none.\n"
    lines = ["Retrieved regulatory context (cite these for any numeric limit):"]
    for c in citations:
        src = "; ".join(c.sources)
        flag = "" if c.review_status == "verified" else " [UNVERIFIED]"
        lines.append(f"- {c.title}" + (f" § {c.heading}" if c.heading else "") + f" ({src}){flag}\n  {c.text}")
    return "\n".join(lines) + "\n"


# --- orchestration ---------------------------------------------------


def _clean_snapshot(snapshot: dict) -> dict:
    s = dict(snapshot)
    s.pop("source", None)  # provenance never reaches the model
    return s


@lru_cache(maxsize=1)
def _taxonomy_digest() -> str:
    """The closed vocabulary the model must choose `cause_id` from.

    An untuned model will otherwise invent labels ("coverage_issue"); rca.py
    rejects those, so without this the served backend 422s constantly. The
    fine-tuned student has this memorised, but the reminder is cheap and keeps
    the two backends behaving the same."""
    lines = ["Valid cause_id values (choose ONLY from these, or null to abstain):"]
    for cid in all_cause_ids():
        c = get_cause(cid)
        lines.append(f"  {cid}  {c['name']}  [{', '.join(c['bands'])}]")
    return "\n".join(lines) + "\n"


def run_diagnosis(snapshot: dict, backend: ModelBackend, cfg: Settings, retriever=None) -> RCAResult:
    snapshot = _clean_snapshot(snapshot)
    citations = retrieve_context(snapshot, cfg, retriever)

    user = (
        _taxonomy_digest()
        + "\n"
        + _context_block(citations)
        + "\nCanonical RF snapshot:\n"
        + json.dumps(snapshot, indent=2, sort_keys=True)
    )
    raw = backend.generate(DIAGNOSIS_SYSTEM, user, temperature=cfg.diagnose_temperature)
    parsed = extract_json(raw)
    if parsed is None:
        raise RCAContractError("model did not return a JSON object")

    parsed.setdefault("ranked_alternatives", [])
    validate_rca(parsed, snapshot, has_citations=bool(citations))
    parsed["citations"] = [c.model_dump() for c in citations]
    return RCAResult.model_validate(parsed)


def run_explanation(snapshot: dict, diagnosis: dict, temperature: float,
                    backend: ModelBackend, cfg: Settings) -> str:
    snapshot = _clean_snapshot(snapshot)
    cause_name = ""
    if diagnosis.get("cause_id"):
        cause_name = get_cause(diagnosis["cause_id"]).get("name", "")
    user = (
        f"Canonical snapshot:\n{json.dumps(snapshot, indent=2, sort_keys=True)}\n\n"
        f"Structured diagnosis" + (f" ({cause_name})" if cause_name else "") + ":\n"
        f"{json.dumps(diagnosis, indent=2)}\n\n"
        "Explain this to a network engineer."
    )
    return backend.generate(EXPLANATION_SYSTEM, user, temperature=temperature).strip()


def run_ask(query: str, temperature: float, backend: ModelBackend, cfg: Settings,
            retriever=None) -> tuple[str, list[Citation]]:
    """Free-text question -> grounded answer, for the Submit/Ask tab.

    No canonical snapshot: the question stands alone, grounded only by
    whatever the RAG index returns for it. Runs at the explanation-band
    temperature (this is prose, not a structured assertion), never the
    diagnosis temperature.
    """
    citations = retrieve_for_text(query, cfg, retriever)
    user = _context_block(citations) + f"\nQuestion:\n{query}\n"
    answer = backend.generate(ASK_SYSTEM, user, temperature=temperature).strip()
    return answer, citations
