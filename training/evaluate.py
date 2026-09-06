"""Evaluate a diagnosis model against the CLAUDE.md targets.

    python -m training.evaluate --eval data/eval.jsonl --responder ollama --model qwen2.5:1.5b-instruct
    python -m training.evaluate --eval data/eval.jsonl --responder adapter --model training/out

Metrics (CLAUDE.md "Evaluation targets"):
  top1_accuracy          predicted cause_id == gold, over non-abstention records
  top3_ambiguous         gold in {cause_id} ∪ {ranked_alternatives}, over kind=ambiguous
  evidence_grounding     every predicted evidence.field_path resolves in the snapshot
  abstention_rate        kind=abstention records where the model returned cause_id null
  hallucination_rate     predictions with a bare numeric regulatory claim

The scoring functions are pure and import nothing heavy — they are unit-tested
directly. Only the responders touch a model.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from data import predicates
from data.teacher import _has_bare_regulatory_number

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# parsing a model's raw text into a prediction dict
# ---------------------------------------------------------------------------


def extract_json(text: str) -> dict | None:
    """Best-effort: pull the first balanced {...} object out of model output."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ---------------------------------------------------------------------------
# pure scoring
# ---------------------------------------------------------------------------


def score_record(meta: dict, snapshot: dict, prediction: dict | None) -> dict:
    """One record's contribution to every metric. All values bool or None.

    None means "this metric does not apply to this record".
    """
    kind = meta["kind"]
    gold = meta["cause_id"]  # None for abstention
    out: dict = {
        "parsed": prediction is not None,
        "top1": None,
        "top3_ambiguous": None,
        "grounded": None,
        "abstained_when_required": None,
        "hallucinated": None,
    }
    if prediction is None:
        # unparseable output fails every metric it is subject to
        out["top1"] = False if kind != "abstention" else None
        out["abstained_when_required"] = False if kind == "abstention" else None
        return out

    pred_id = prediction.get("cause_id")
    alts = [a.get("cause_id") for a in prediction.get("ranked_alternatives", []) if isinstance(a, dict)]

    if kind == "abstention":
        out["abstained_when_required"] = pred_id is None
    else:
        out["top1"] = pred_id == gold
    if kind == "ambiguous":
        out["top3_ambiguous"] = gold in ([pred_id] + alts)

    ev = prediction.get("evidence") or []
    if not ev:
        # abstention legitimately cites nothing; an asserted cause with no
        # evidence has failed grounding.
        out["grounded"] = None if kind == "abstention" else False
    else:
        grounded = True
        for item in ev:
            path = (item or {}).get("field_path")
            if not isinstance(path, str):
                grounded = False
                continue
            try:
                hits = predicates.select(snapshot, predicates.parse_path(path))
            except predicates.PredicateError:
                grounded = False
                continue
            if not [v for v in hits if v is not None]:
                grounded = False
        out["grounded"] = grounded

    prose = [str((i or {}).get("why_it_matters", "")) for i in ev]
    prose += [str(x) for x in (prediction.get("remediation") or [])]
    out["hallucinated"] = any(_has_bare_regulatory_number(p) for p in prose)
    return out


def aggregate(scores: list[dict]) -> dict:
    def rate(key):
        vals = [s[key] for s in scores if s[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "n": len(scores),
        "parse_rate": rate("parsed"),
        "top1_accuracy": rate("top1"),
        "top3_ambiguous": rate("top3_ambiguous"),
        "evidence_grounding": rate("grounded"),
        "abstention_rate": rate("abstained_when_required"),
        "hallucination_rate": rate("hallucinated"),
    }


# ---------------------------------------------------------------------------
# responders
# ---------------------------------------------------------------------------


class EchoResponder:
    """Returns the gold assistant turn — used to unit-test the harness itself."""

    def __call__(self, messages: list[dict]) -> str:
        return messages[-1]["content"]


class OllamaResponder:
    def __init__(self, model: str, host: str = "http://localhost:11434", temperature: float = 0.15):
        import os
        self.model = model
        self.host = (os.environ.get("OLLAMA_HOST") or host).rstrip("/")
        self.temperature = temperature

    def __call__(self, messages: list[dict]) -> str:
        import urllib.request

        sys_user = [m for m in messages if m["role"] != "assistant"]
        body = json.dumps(
            {"model": self.model, "stream": False,
             "options": {"temperature": self.temperature}, "messages": sys_user}
        ).encode()
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return (json.loads(resp.read()).get("message") or {}).get("content", "")


class AdapterResponder:
    """Base model + trained LoRA adapter, at the diagnosis temperature."""

    def __init__(self, adapter_dir: str, base_model: str | None = None, temperature: float = 0.15):
        import torch
        from peft import PeftConfig, PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        pc = PeftConfig.from_pretrained(adapter_dir)
        base = base_model or pc.base_model_name_or_path
        self.tok = AutoTokenizer.from_pretrained(adapter_dir)
        model = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.bfloat16, device_map="auto")
        self.model = PeftModel.from_pretrained(model, adapter_dir)
        self.model.eval()
        self.temperature = temperature

    def __call__(self, messages: list[dict]) -> str:
        sys_user = [m for m in messages if m["role"] != "assistant"]
        inputs = self.tok.apply_chat_template(
            sys_user, add_generation_prompt=True, return_tensors="pt"
        ).to(self.model.device)
        out = self.model.generate(
            inputs, max_new_tokens=800, do_sample=self.temperature > 0,
            temperature=max(self.temperature, 1e-3),
        )
        return self.tok.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)


_RESPONDERS = {"echo": EchoResponder, "ollama": OllamaResponder, "adapter": AdapterResponder}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def run(eval_path: Path, responder) -> dict:
    scores, by_kind = [], Counter()
    with open(eval_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            meta = rec["meta"]
            by_kind[meta["kind"]] += 1
            snapshot = json.loads(rec["messages"][1]["content"])
            raw = responder(rec["messages"])
            scores.append(score_record(meta, snapshot, extract_json(raw)))
    report = aggregate(scores)
    report["by_kind"] = dict(by_kind)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eval", type=Path, default=REPO / "data" / "eval.jsonl")
    ap.add_argument("--responder", choices=list(_RESPONDERS), default="ollama")
    ap.add_argument("--model", default="qwen2.5:1.5b-instruct",
                    help="ollama tag, or adapter dir for --responder adapter")
    ap.add_argument("--base-model", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.responder == "echo":
        responder = EchoResponder()
    elif args.responder == "ollama":
        responder = OllamaResponder(args.model)
    else:
        responder = AdapterResponder(args.model, args.base_model)

    report = run(args.eval, responder)
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
