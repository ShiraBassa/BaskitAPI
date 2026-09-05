from __future__ import annotations

import argparse
import json
from pathlib import Path


def convert(src: Path, dst: Path):
    rows = []

    system_prompt = (
        "Parse the product name into semantic segments. "
        "Return JSON with a segments array. Each segment must contain text, role, and kind. "
        "Allowed roles are product, brand, attribute, and unclassified. "
        "For attributes, kind MUST be written in Hebrew. "
        "Use the following Hebrew attribute kinds when applicable: טעם, ריח, צבע, חומר, גודל, סוג, כמות, משקל, נפח, מספר יחידות. "
        "Do not translate, invent, or mix attribute-kind languages. "
        "Preserve the original product text exactly in segment text, and group words according to their semantic role."
    )

    for line_no, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue

        record = json.loads(line)
        if "text" not in record or "segments" not in record:
            raise ValueError(
                f"line {line_no}: expected text and segments in Hebrew training record"
            )

        product_name = record["text"]
        answer = json.dumps(
            {"segments": record["segments"]}, ensure_ascii=False
        )

        rows.append(
            {
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": f"Product name: {product_name}",
                    },
                    {
                        "role": "assistant",
                        "content": answer,
                    },
                ]
            }
        )

    dst.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} examples to {dst}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="baskit_training_examples_hebrew_v1.jsonl")
    ap.add_argument("--output", default="sft_train_hebrew_v1.jsonl")
    args = ap.parse_args()
    convert(Path(args.input), Path(args.output))
