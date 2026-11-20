"""Merge the phase-5 LoRA adapter into its base model and register it with Ollama.

    python scripts/export_ollama.py                       # training/out -> Ollama model "rf-slm"
    python scripts/export_ollama.py --adapter path/to/out --name rf-slm --quant q4_K_M
    python scripts/export_ollama.py --skip-create         # merge + Modelfile only

Why this exists: serving the adapter through `RF_SLM_BACKEND=adapter` loads a
~3 GB half-precision model, which spills off a small GPU (e.g. a 2 GB MX550)
onto the CPU. Merged and quantized by Ollama to Q4_K_M, the 1.5B student is
~1 GB and fits on that card with room for an 8k context. Serve it with:

    RF_SLM_BACKEND=ollama RF_SLM_DIAGNOSE_MODEL=rf-slm uvicorn backend.main:app --port 8090

The merge runs on CPU in fp16 (~6 GB RAM, a few minutes) -- no GPU needed.
Needs requirements-train.txt (torch/transformers/peft; CPU torch is fine).

Temperature is deliberately NOT baked into the Modelfile: the backend sends
the stage-appropriate temperature on every request (CLAUDE.md decision #3), and
a Modelfile default would only mislead anyone calling the model directly.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Qwen2.5 ChatML, messages-based so /api/chat system+user turns render exactly
# as the student saw them in training (tokenizer.apply_chat_template).
_TEMPLATE = (
    "{{- range .Messages }}<|im_start|>{{ .Role }}\n"
    "{{ .Content }}<|im_end|>\n"
    "{{ end }}<|im_start|>assistant\n"
)


def modelfile(num_ctx: int) -> str:
    return (
        "FROM .\n"
        f'TEMPLATE """{_TEMPLATE}"""\n'
        'PARAMETER stop "<|im_end|>"\n'
        'PARAMETER stop "<|endoftext|>"\n'
        f"PARAMETER num_ctx {num_ctx}\n"
    )


def merge(adapter: Path, out: Path, base: str | None) -> None:
    try:
        import torch
        from peft import PeftConfig, PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as exc:
        raise SystemExit(f"needs the training deps ({exc}): pip install -r requirements-train.txt")

    if not (adapter / "adapter_config.json").exists():
        raise SystemExit(f"no LoRA adapter at {adapter} (expected adapter_config.json)")
    base = base or PeftConfig.from_pretrained(adapter).base_model_name_or_path
    print(f"merging {adapter} into {base} (fp16, CPU) ...")
    model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.float16, device_map="cpu")  # transformers>=5: torch_dtype -> dtype
    model = PeftModel.from_pretrained(model, str(adapter)).merge_and_unload()
    if out.exists():
        shutil.rmtree(out)
    model.save_pretrained(out, safe_serialization=True)
    AutoTokenizer.from_pretrained(adapter).save_pretrained(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", type=Path, default=REPO / "training" / "out")
    ap.add_argument("--base-model", default=None, help="override the adapter's recorded base model")
    ap.add_argument("--out", type=Path, default=REPO / ".local" / "merged", help="merged model dir (git-ignored)")
    ap.add_argument("--name", default="rf-slm", help="Ollama model name")
    ap.add_argument("--quant", default="q4_K_M", help="Ollama quantization (q4_K_M ~1 GB, q8_0 ~1.7 GB)")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--skip-create", action="store_true", help="merge + write Modelfile, don't call ollama")
    args = ap.parse_args(argv)

    merge(args.adapter, args.out, args.base_model)
    (args.out / "Modelfile").write_text(modelfile(args.num_ctx), encoding="utf-8")
    print(f"merged model + Modelfile in {args.out}")
    if args.skip_create:
        print(f"next:  cd {args.out} && ollama create {args.name} -q {args.quant} -f Modelfile")
        return 0

    cmd = ["ollama", "create", args.name, "-q", args.quant, "-f", "Modelfile"]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=args.out)
    if rc == 0:
        print(f"\nOllama model {args.name!r} ready. Score it:\n"
              f"  python -m training.evaluate --responder ollama --model {args.name}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
