from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="mlx-community/Qwen3.5-9B-MLX-4bit")
    ap.add_argument("--train", default="sft_train_hebrew_v1.jsonl")
    ap.add_argument("--output", default="outputs/baskit-qwen-lora")
    ap.add_argument("--epochs", type=float, default=2.0)
    args = ap.parse_args()

    train_path = Path(args.train)
    output_path = Path(args.output)
    model_path = Path(args.model)

    if not train_path.exists():
        raise FileNotFoundError(f"Training dataset not found: {train_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="baskit_mlx_data_") as data_dir:
        data_path = Path(data_dir) / "train.jsonl"
        shutil.copy2(train_path, data_path)

        run([
            sys.executable,
            "-m",
            "mlx_lm.lora",
            "--model",
            str(model_path),
            "--data",
            str(data_dir),
            "--train",
            "--iters",
            str(max(1, round(len(train_path.read_text(encoding='utf-8').splitlines()) * args.epochs))),
            "--batch-size",
            "1",
            "--num-layers",
            "4",
            "--learning-rate",
            "5e-5",
            "--adapter-path",
            str(output_path),
            "--max-seq-length",
            "512",
        ])

    print(f"Saved LoRA adapter to {output_path}")


if __name__ == "__main__":
    main()
