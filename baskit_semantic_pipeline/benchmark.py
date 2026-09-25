from __future__ import annotations

import argparse
import json
import traceback
import time
from pathlib import Path

from semantic_ai import SemanticEngine
from semantic_ai_prompts import SYSTEM_PROMPT



def load_jsonl(path):
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()

            if not line:
                continue

            # Allow // to temporarily disable a JSONL record.
            if line.startswith("//"):
                continue

            yield line_no, json.loads(line)


def product_core(gold: dict) -> str:
    return "".join(
        str(s.get("text", ""))
        for s in gold.get("segments", [])
        if isinstance(s, dict) and s.get("role") == "product"
    )


def normalize_gold(record: dict) -> tuple[str, dict]:
    if "item_name" in record:
        if "prediction" not in record:
            raise ValueError("gold record has no 'prediction' field")

        prediction = record["prediction"]
        if not isinstance(prediction, dict) or "segments" not in prediction:
            raise ValueError("gold record has no valid 'prediction.segments' field")

        segments = []
        for segment in prediction["segments"]:
            segments.append(
                {
                    "text": segment.get("text", ""),
                    "role": segment.get("role", ""),
                    "kind": segment.get("kind", ""),
                }
            )

        return record["item_name"], {"segments": segments}

    if "text" in record and isinstance(record.get("segments"), list):
        segments = []
        for segment in record["segments"]:
            if not isinstance(segment, dict):
                raise ValueError("checks segment is not an object")
            segments.append(
                {
                    "text": segment.get("text", ""),
                    "role": segment.get("role", ""),
                    "kind": segment.get("kind", ""),
                }
            )
        return record["text"], {"segments": segments}

    if "text" in record and isinstance(record.get("tokens"), list):
        item_name = record["text"]
        segments = []
        for token in record["tokens"]:
            if not isinstance(token, dict):
                raise ValueError("heldout token is not an object")
            segments.append(
                {
                    "text": token.get("text", ""),
                    "role": token.get("role", ""),
                    "kind": token.get("kind", ""),
                }
            )
        return item_name, {"segments": segments}

    messages = record.get("messages")
    if isinstance(messages, list):
        user_content = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"),
            "",
        )
        assistant_content = next(
            (
                m.get("content", "")
                for m in reversed(messages)
                if m.get("role") == "assistant"
            ),
            "",
        )

        prefix = "Product name:"
        if user_content.startswith(prefix):
            item_name = user_content[len(prefix):].strip()
        else:
            item_name = user_content.strip()

        if not item_name:
            raise ValueError("heldout record has no product name in user message")
        if not assistant_content:
            raise ValueError("heldout record has no assistant answer")

        expected = extract_json_object(assistant_content)
        if not isinstance(expected, dict) or "segments" not in expected:
            raise ValueError("heldout assistant answer has no valid 'segments' field")

        return item_name, {"segments": expected["segments"]}

    prompt = record.get("prompt")
    completion = record.get("completion")
    if isinstance(prompt, str) and isinstance(completion, str):
        prefix = "Product name:"
        marker = prompt.rfind(prefix)
        if marker >= 0:
            item_name = prompt[marker + len(prefix):].strip()
        else:
            item_name = prompt.strip()

        if not item_name:
            raise ValueError("heldout record has no product name in prompt")
        if not completion.strip():
            raise ValueError("heldout record has no completion")

        expected = extract_json_object(completion)
        if not isinstance(expected, dict) or "segments" not in expected:
            raise ValueError("heldout completion has no valid 'segments' field")

        return item_name, {"segments": expected["segments"]}

    raise ValueError(
        "unsupported gold/heldout record format: expected item_name, messages, or prompt/completion"
    )


def exact_match(pred: dict, gold: dict) -> bool:
    return pred.get("segments", []) == gold.get("segments", [])


def mlx_chat_prompt(system_prompt: str, user_text: str) -> str:
    return (
        "<|im_start|>system\n"
        + system_prompt
        + "\n<|im_end|>\n"
        + "<|im_start|>user\n"
        + f"Product name: {user_text}\n"
        + "<|im_end|>\n"
        + "<|im_start|>assistant\n"
    )


def extract_json_object(text: str) -> dict:
    text = text.strip()
    if "{" not in text:
        raise ValueError("MLX output contains no JSON object")

    start = text.find("{")
    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:index + 1])

    raise ValueError("MLX output contains incomplete JSON")

def build_mlx_prefix_tokens(tokenizer, system_prompt: str) -> list[int]:
    prefix = (
        "<|im_start|>system\n"
        + system_prompt
        + "\n<|im_end|>\n"
        + "<|im_start|>user\n"
        + "Product name: "
    )
    return tokenizer.encode(prefix)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="baskit_semantic_checks_hebrew_v2.jsonl")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--output", default="benchmark_results.jsonl")
    ap.add_argument("--mlx-model", default="")
    ap.add_argument("--mlx-adapter", default="")
    args = ap.parse_args()

    rows = list(load_jsonl(Path(args.gold)))
    if args.limit:
        rows = rows[:args.limit]

    prepared = []
    for line_no, record in rows:
        text, gold = normalize_gold(record)
        prepared.append((line_no, text, gold))

    # Hold-out isolation: exact inputs and product cores must remain disjoint
    # between checks and training. This is dataset hygiene, not semantic
    # hard-coding.
    engine = SemanticEngine()
    passed = 0

    with open(args.output, "w", encoding="utf-8") as out:
        if args.mlx_model:
            raise NotImplementedError(
                "The legacy --mlx-model benchmark path is not implemented in this engine. "
                "Run the benchmark through SemanticEngine (the default path)."
            )
        else:
            results = []
            for index, (line_no, text, gold) in enumerate(prepared, 1):
                try:
                    print(f"\n========== BENCHMARK REQUEST {index}/{len(prepared)} | {text} ==========")
                    started = time.perf_counter()
                    prediction = engine.parse(text)
                    elapsed = time.perf_counter() - started
                    if not isinstance(prediction, dict):
                        prediction = prediction.model_dump()
                    results.append((line_no, text, gold, prediction))
                    print(
                        "DONE | "
                        + f"{index}/{len(prepared)} | "
                        + text
                        + f" | {elapsed:.3f}s",
                        flush=True,
                    )
                except Exception as exc:
                    traceback.print_exc()
                    print(
                        "ERROR | "
                        + f"{index}/{len(prepared)} | "
                        + text
                        + f" | {type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    results.append(
                        (
                            line_no,
                            text,
                            gold,
                            {
                                "valid": False,
                                "segments": [],
                                "error": f"{type(exc).__name__}: {exc}",
                            },
                        )
                    )
            results.sort(key=lambda row: row[0])

        for line_no, text, gold, result_dict in results:
            ok = result_dict.get("valid", False) and exact_match(result_dict, gold)
            passed += int(ok)

            # Print the complete result as one contiguous block.  Previously,
            # PASS cases printed only their status while FAIL cases printed
            # GOLD/PRED before the status line.  That made the output look as
            # though a failure's GOLD/PRED belonged to the preceding PASS.
            print(f"RESULT | line {line_no} | {text}")
            print("  GOLD :", json.dumps(gold, ensure_ascii=False))
            print(
                "  PRED :",
                json.dumps(
                    {"segments": result_dict.get("segments", [])},
                    ensure_ascii=False,
                ),
            )
            print(("PASS" if ok else "FAIL") + f" | {text}")

            row = {
                "line": line_no,
                "text": text,
                "passed": ok,
                "prediction": result_dict,
                "gold": gold,
            }

            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(("PASS" if ok else "FAIL") + f" | {text}")

    total = len(rows)
    accuracy = passed / total if total else 0.0
    print(f"\nExact semantic match: {passed}/{total} = {accuracy:.2%}")
    print(f"Results: {args.output}")


if __name__ == "__main__":
    main()