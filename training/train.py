"""QLoRA SFT of the RF root-cause student.

    python -m training.train --dry-run                 # no GPU, no heavy deps
    python -m training.train --config training/qlora_config.yaml   # on the GPU box

`--dry-run` loads the YAML, checks the dataset files parse as chat records,
renders the first example through the tokenizer's chat template (if transformers
is importable) or a plain concatenation (if not), prints the training plan, and
exits 0 without importing torch. Use it in CI and before every real run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key in ("base_model", "data", "lora", "training", "quantization"):
        if key not in cfg:
            raise SystemExit(f"config missing top-level key: {key!r}")
    return cfg


def read_chat_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(
            f"dataset not found: {path}\n"
            "  run:  python -m data.generate --count 3000 --out data/"
        )
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            msgs = rec.get("messages")
            if not msgs or msgs[-1]["role"] != "assistant":
                raise SystemExit(f"{path}:{i}: not a chat record ending in an assistant turn")
            records.append(rec)
    return records


def _plan(cfg: dict, n_train: int, n_eval: int) -> str:
    t = cfg["training"]
    eff_batch = t["per_device_train_batch_size"] * t["gradient_accumulation_steps"]
    steps_per_epoch = max(1, n_train // eff_batch)
    return (
        f"  base model      {cfg['base_model']}\n"
        f"  train / eval    {n_train} / {n_eval} examples\n"
        f"  LoRA            r={cfg['lora']['r']} alpha={cfg['lora']['alpha']} "
        f"dropout={cfg['lora']['dropout']} on {len(cfg['lora']['target_modules'])} modules\n"
        f"  quant           4-bit {cfg['quantization']['bnb_4bit_quant_type']}, "
        f"compute {cfg['quantization']['bnb_4bit_compute_dtype']}\n"
        f"  effective batch {eff_batch}  (~{steps_per_epoch} steps/epoch, "
        f"{t['num_train_epochs']} epochs)\n"
        f"  lr              {t['learning_rate']} {t['lr_scheduler_type']}, "
        f"warmup {t['warmup_ratio']}\n"
        f"  output_dir      {t['output_dir']}"
    )


def dry_run(cfg: dict) -> int:
    train = read_chat_jsonl(REPO / cfg["data"]["train_file"])
    eval_ = read_chat_jsonl(REPO / cfg["data"]["eval_file"])
    print("QLoRA dry run — config and dataset OK\n")
    print(_plan(cfg, len(train), len(eval_)))

    example = train[0]["messages"]
    print("\nfirst example, rendered:\n" + "-" * 60)
    try:
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(cfg["base_model"])
        text = tok.apply_chat_template(example, tokenize=False)
    except Exception as exc:  # transformers missing, or model not cached
        print(f"(chat template unavailable: {exc}; showing raw)")
        text = "\n".join(f"<{m['role']}>\n{m['content']}" for m in example)
    print(text[:2000])
    print("-" * 60)
    print("\nconfig + data OK. on the GPU box:  python -m training.train")
    return 0


def train(cfg: dict) -> int:
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise SystemExit(
            f"training dependencies missing ({exc}).\n"
            "  pip install -r requirements.txt -r requirements-train.txt\n"
            "  (or use --dry-run, which needs none of them)"
        )

    q = cfg["quantization"]
    bnb = BitsAndBytesConfig(
        load_in_4bit=q["load_in_4bit"],
        bnb_4bit_quant_type=q["bnb_4bit_quant_type"],
        bnb_4bit_use_double_quant=q["bnb_4bit_use_double_quant"],
        bnb_4bit_compute_dtype=getattr(torch, q["bnb_4bit_compute_dtype"]),
    )
    tokenizer = AutoTokenizer.from_pretrained(cfg["base_model"])
    model = AutoModelForCausalLM.from_pretrained(
        cfg["base_model"], quantization_config=bnb, device_map="auto"
    )

    lora = LoraConfig(
        r=cfg["lora"]["r"],
        lora_alpha=cfg["lora"]["alpha"],
        lora_dropout=cfg["lora"]["dropout"],
        bias=cfg["lora"]["bias"],
        task_type=cfg["lora"]["task_type"],
        target_modules=cfg["lora"]["target_modules"],
    )

    def to_ds(path):
        return Dataset.from_list(
            [{"messages": r["messages"]} for r in read_chat_jsonl(REPO / path)]
        )

    train_ds = to_ds(cfg["data"]["train_file"])
    eval_ds = to_ds(cfg["data"]["eval_file"])

    t = cfg["training"]
    # trl>=1.0's SFTConfig (via transformers>=5's TrainingArguments) dropped
    # warmup_ratio entirely -- only warmup_steps remains. Convert here so the
    # config file can keep expressing warmup as a ratio.
    steps_per_epoch = -(-len(train_ds) // (t["per_device_train_batch_size"] * t["gradient_accumulation_steps"]))
    warmup_steps = round(steps_per_epoch * t["num_train_epochs"] * t["warmup_ratio"])
    sft = SFTConfig(
        output_dir=t["output_dir"],
        num_train_epochs=t["num_train_epochs"],
        per_device_train_batch_size=t["per_device_train_batch_size"],
        per_device_eval_batch_size=t.get("per_device_eval_batch_size", t["per_device_train_batch_size"]),
        gradient_accumulation_steps=t["gradient_accumulation_steps"],
        learning_rate=t["learning_rate"],
        lr_scheduler_type=t["lr_scheduler_type"],
        warmup_steps=warmup_steps,
        weight_decay=t["weight_decay"],
        logging_steps=t["logging_steps"],
        eval_strategy=t["eval_strategy"],
        eval_steps=t["eval_steps"],
        save_strategy=t["save_strategy"],
        save_steps=t["save_steps"],
        save_total_limit=t["save_total_limit"],
        bf16=t["bf16"],
        fp16=not t["bf16"],  # Turing cards (T4, RTX 20xx) have no bf16
        gradient_checkpointing=t["gradient_checkpointing"],
        optim=t["optim"],
        seed=t["seed"],
        max_length=cfg["data"]["max_seq_length"],  # trl>=1.0 renamed SFTConfig's max_seq_length -> max_length
        # trl masks everything up to the last assistant turn when given chat data
        assistant_only_loss=cfg["data"].get("mask_prompt", True),
        packing=False,
    )
    trainer = SFTTrainer(
        model=model,
        args=sft,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        peft_config=lora,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(t["output_dir"])
    tokenizer.save_pretrained(t["output_dir"])
    print(f"adapter saved to {t['output_dir']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO / "training" / "qlora_config.yaml")
    ap.add_argument("--dry-run", action="store_true", help="validate config + data, no GPU")
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    return dry_run(cfg) if args.dry_run else train(cfg)


if __name__ == "__main__":
    sys.exit(main())
