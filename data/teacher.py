"""Teacher model client (local Ollama), with a deterministic offline fallback.

The teacher only ever writes *language* — one-sentence evidence rationales and
reworded remediation intent. It never decides `cause_id`, never produces field
paths, never emits numbers. That keeps a weak local model from corrupting the
structural ground truth the builder already established.

Ollama HTTP API: POST {host}/api/chat with stream=false, read
response["message"]["content"]. stdlib only — no `requests`/`ollama` dependency.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from data import prompts
from data.predicates import PredicateError, parse_path

DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("RF_SLM_TEACHER_MODEL", "qwen2.5:7b-instruct")


class TeacherUnavailable(RuntimeError):
    """Ollama could not be reached / the model is not pulled."""


class Teacher:
    def __init__(
        self,
        *,
        enabled: bool = True,
        model: str = DEFAULT_MODEL,
        host: str = DEFAULT_HOST,
        temperature: float = 0.4,
        timeout: float = 60.0,
    ) -> None:
        self.enabled = enabled
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    # -- transport --------------------------------------------------------

    def _chat(self, system: str, user: str) -> str:
        body = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "options": {"temperature": self.temperature},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/chat", data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise TeacherUnavailable(
                f"could not reach Ollama at {self.host} (model {self.model!r}): {exc}"
            ) from exc
        return (payload.get("message") or {}).get("content", "").strip()

    def health_check(self) -> None:
        """Raise TeacherUnavailable unless the configured model answers."""
        if not self.enabled:
            return
        out = self._chat("Reply with the single word OK.", "ping")
        if not out:
            raise TeacherUnavailable(f"empty response from {self.model!r}")

    # -- language tasks --------------------------------------------------

    def why_it_matters(self, cause: dict, field_path: str, observed_value) -> str:
        if self.enabled:
            try:
                text = self._chat(
                    prompts.TEACHER_WHY_SYSTEM,
                    prompts.TEACHER_WHY_USER.format(
                        cause_name=cause["name"],
                        cause_description=" ".join(cause["description"].split()),
                        field_path=field_path,
                        observed_value=observed_value,
                    ),
                )
                text = _first_sentence(text)
                if text and not _has_bare_regulatory_number(text):
                    return text
            except TeacherUnavailable:
                pass
        return _template_why(cause, field_path, observed_value)

    def narrate(
        self, cause: dict, evidence: list[dict], evidence_summary: str
    ) -> tuple[list[str], list[str]]:
        """ONE teacher call per example: a one-sentence rationale per evidence
        item. Returns (rationales, remediation).

        Remediation is NOT sent to the teacher — the `remediation_intent` lines
        in the taxonomy are curated and vendor-neutral, and letting a 7B model
        reword them on CPU both doubled the per-example latency and introduced
        drift (lost 1/6/11 specificity, invented "better utilization"). For this
        project precision beats fluency, so remediation is used verbatim. The
        student can be taught evidence-conditioned adaptation in a later pass.

        Batching the rationales into one call instead of one call per field is
        the difference between a ~3k run taking ~day and taking several.
        """
        intents = list(cause.get("remediation_intent", []))
        rationales = [
            _template_why(cause, e["field_path"], e["observed_value"]) for e in evidence
        ]
        if not self.enabled or not evidence:
            return rationales, intents

        obs = "\n".join(
            f"{i+1}. {e['field_path']} = {e['observed_value']}" for i, e in enumerate(evidence)
        )
        user = prompts.TEACHER_NARRATE_USER.format(
            cause_name=cause["name"],
            cause_description=" ".join(cause["description"].split()),
            observations=obs,
            n=len(evidence),
        )
        try:
            data = _extract_json(self._chat(prompts.TEACHER_NARRATE_SYSTEM, user))
        except TeacherUnavailable:
            return rationales, intents
        if not isinstance(data, dict):
            return rationales, intents

        got = data.get("rationales")
        if isinstance(got, list) and len(got) == len(evidence):
            for i, r in enumerate(got):
                r = _first_sentence(str(r))
                if r and not _has_bare_regulatory_number(r):
                    rationales[i] = r
        return rationales, intents

    def remediation(self, cause: dict, evidence_summary: str) -> list[str]:
        intents = list(cause.get("remediation_intent", []))
        if self.enabled:
            try:
                text = self._chat(
                    prompts.TEACHER_REMEDIATION_SYSTEM,
                    prompts.TEACHER_REMEDIATION_USER.format(
                        cause_name=cause["name"],
                        evidence_summary=evidence_summary,
                        intent_lines="\n".join(f"- {i}" for i in intents),
                    ),
                )
                lines = [
                    ln.strip(" -•\t")
                    for ln in text.splitlines()
                    if ln.strip(" -•\t")
                ]
                lines = [ln for ln in lines if not _has_bare_regulatory_number(ln)]
                if lines:
                    return lines
            except TeacherUnavailable:
                pass
        return intents


# --- offline templates & guards ------------------------------------------

# "2.4 GHz" / "5GHz" / "6 GHz" are band names, not spectrum claims — strip them
# before looking for a bare numeric limit.
_BAND_NAME = re.compile(r"\b(?:2\.4|5|6)\s?GHz\b", re.I)
_REGULATORY_NUMBER = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:MHz|GHz|dBm|dBi|dB|mW|ms|µs)\b", re.I
)


def _has_bare_regulatory_number(text: str) -> bool:
    """A number+unit with no citation marker — the hallucination pattern."""
    text = _BAND_NAME.sub("", text)
    if not _REGULATORY_NUMBER.search(text):
        return False
    return not re.search(r"\b(per|cites?|corpus|standard|clause|regulat)", text, re.I)


def _extract_json(text: str) -> dict | None:
    """First balanced {...} object in the model's reply, or None."""
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


def _first_sentence(text: str) -> str:
    text = text.strip().strip('"')
    for sep in (". ", "\n"):
        if sep in text:
            return text.split(sep)[0].strip().rstrip(".") + "."
    return text if text.endswith(".") or not text else text + "."


def _template_why(cause: dict, field_path: str, observed_value) -> str:
    try:
        leaf = parse_path(field_path)[-1][0]
    except PredicateError:
        leaf = field_path.rsplit(".", 1)[-1]
    return (
        f"The observed {leaf} is in the range this cause requires, one of the "
        f"gating conditions for \"{cause['name']}\"."
    )
