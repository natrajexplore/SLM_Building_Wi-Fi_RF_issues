"""Merge the phase-5 LoRA adapter into its base model and register it with Ollama.

    python scripts/export_ollama.py                       # training/out -> Ollama model "rf-slm"
    python scripts/export_ollama.py --adapter path/to/out --name rf-slm --quant q8_0
    python scripts/export_ollama.py --skip-create         # merge + GGUF + Modelfile only

Needs a llama.cpp checkout for its GGUF converter (default .local/llama.cpp):
    git clone --depth 1 https://github.com/ggml-org/llama.cpp .local/llama.cpp

Why this exists: serving the adapter through `RF_SLM_BACKEND=adapter` loads a
~3 GB half-precision model, which spills off a small GPU (e.g. a 2 GB MX550)
onto the CPU. Merged and converted to a Q8_0 GGUF the 1.5B student is ~1.6 GB
(near-lossless). Ollama >= 0.40 can't import Qwen2 safetensors itself, hence
the GGUF step. Serve it with:

    RF_SLM_BACKEND=ollama RF_SLM_DIAGNOSE_MODEL=rf-slm uvicorn backend.main:app --port 8090

The merge runs on CPU in fp16 (~6 GB RAM, a few minutes) -- no GPU needed.
Needs requirements-train.txt (torch/transformers/peft; CPU torch is fine) plus
`sentencepiece` (the converter imports it before falling back to Qwen's BPE).

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


def modelfile(num_ctx: int, source: str = ".") -> str:
    return (
        f"FROM {source}\n"
        f'TEMPLATE """{_TEMPLATE}"""\n'
        'PARAMETER stop "<|im_end|>"\n'
        'PARAMETER stop "<|endoftext|>"\n'
        # Ollama's default repeat_penalty (>1) taxes the tokens structured JSON
        # repeats constantly (quotes, field names); it flipped the student from
        # a 67-85%-likely cause_id to "null" on every eval record. Off.
        "PARAMETER repeat_penalty 1\n"
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
    # The base model's own tokenizer files, not the adapter's: transformers 5
    # re-saves the tokenizer without vocab.json/merges.txt, which llama.cpp's
    # GGUF converter needs. LoRA doesn't touch the vocab, so they're identical.
    AutoTokenizer.from_pretrained(base).save_pretrained(out)
    from huggingface_hub import hf_hub_download
    for name in ("tokenizer.json", "tokenizer_config.json", "vocab.json", "merges.txt"):
        try:
            shutil.copy(hf_hub_download(base, name), out / name)
        except Exception:  # local/non-hub base: keep what save_pretrained wrote
            pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--adapter", type=Path, default=REPO / "training" / "out")
    ap.add_argument("--base-model", default=None, help="override the adapter's recorded base model")
    ap.add_argument("--out", type=Path, default=REPO / ".local" / "merged", help="merged model dir (git-ignored)")
    ap.add_argument("--name", default="rf-slm", help="Ollama model name")
    ap.add_argument("--quant", default="q8_0", help="GGUF type from convert_hf_to_gguf.py (q8_0 ~1.6 GB, f16 ~3 GB)")
    ap.add_argument("--llama-cpp", type=Path, default=REPO / ".local" / "llama.cpp",
                    help="llama.cpp checkout (git clone --depth 1 https://github.com/ggml-org/llama.cpp)")
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--skip-create", action="store_true", help="merge + GGUF + Modelfile, don't call ollama")
    args = ap.parse_args(argv)

    # Ollama >= 0.40 imports safetensors through MLX, which rejects
    # Qwen2ForCausalLM ("unsupported MLX architecture"), and only quantizes
    # safetensors imports. So: merge -> GGUF (llama.cpp converter) -> import.
    converter = args.llama_cpp / "convert_hf_to_gguf.py"
    if not converter.exists():
        raise SystemExit(f"no {converter}: git clone --depth 1 https://github.com/ggml-org/llama.cpp {args.llama_cpp}")
    merge(args.adapter, args.out, args.base_model)
    gguf = f"{args.name}-{args.quant}.gguf"
    rc = subprocess.call([sys.executable, str(converter), str(args.out), "--outtype", args.quant,
                          "--outfile", str(args.out / gguf)])
    if rc:
        return rc
    (args.out / "Modelfile").write_text(modelfile(args.num_ctx, f"./{gguf}"), encoding="utf-8")
    print(f"merged model, {gguf} + Modelfile in {args.out}")
    if args.skip_create:
        print(f"next:  cd {args.out} && ollama create {args.name} -f Modelfile")
        return 0

    cmd = ["ollama", "create", args.name, "-f", "Modelfile"]
    print("running:", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=args.out)
    if rc == 0:
        print(f"\nOllama model {args.name!r} ready. Score it:\n"
              f"  python -m training.evaluate --responder ollama --model {args.name}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
