from __future__ import annotations

import json
import time
from pathlib import Path

from semantic_ai import SemanticEngine
from semantic_ai_config import CONFIG


GOLD = Path(__file__).resolve().parent / "baskit_semantic_checks_hebrew_v2.jsonl"


def load_rows(limit: int = 0):
    rows = []
    with GOLD.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            record = json.loads(line)
            if "item_name" in record:
                text = record["item_name"]
                gold = record["prediction"]
            elif "text" in record and isinstance(record.get("segments"), list):
                text = record["text"]
                gold = {"segments": record["segments"]}
            else:
                continue
            rows.append((line_no, text, gold))
            if limit and len(rows) >= limit:
                break
    return rows


def profile(limit: int = 106):
    engine = SemanticEngine()
    original_chat = engine.llm._chat
    calls = []

    def timed_chat(messages, system_prompt=None, response_schema=None):
        t0 = time.perf_counter()
        response = original_chat(messages, system_prompt=system_prompt, response_schema=response_schema)
        elapsed = time.perf_counter() - t0
        last_user = messages[-1].get("content", "") if messages else ""
        stage = "repair" if "Validation errors:" in last_user else "fast_parse"
        calls.append({
            "stage": stage,
            "seconds": elapsed,
            "system_chars": len(system_prompt if system_prompt is not None else engine.llm._system_message["content"]),
            "user_chars": len(last_user),
        })
        return response

    engine.llm._chat = timed_chat

    rows = load_rows(limit)
    total_t0 = time.perf_counter()
    results = []
    for i, (line_no, text, gold) in enumerate(rows, 1):
        before = len(calls)
        t0 = time.perf_counter()
        prediction = engine.parse(text)
        elapsed = time.perf_counter() - t0
        own_calls = calls[before:]
        exact = prediction.get("segments", []) == gold.get("segments", [])
        results.append({
            "index": i,
            "line": line_no,
            "text": text,
            "seconds": elapsed,
            "exact": exact,
            "llm_calls": len(own_calls),
            "calls": own_calls,
            "valid": prediction.get("valid"),
            "validation_errors": prediction.get("validation_errors", []),
        })
        print(f"{i:3d}/{len(rows)} | {elapsed:8.3f}s | calls={len(own_calls)} | exact={exact} | {text}", flush=True)

    total = time.perf_counter() - total_t0
    durations = [r["seconds"] for r in results]
    slow = sorted(results, key=lambda r: r["seconds"], reverse=True)[:15]
    call_durations = [c["seconds"] for c in calls]

    print("\n===== PROFILE SUMMARY =====")
    print(f"cases: {len(results)}")
    print(f"exact: {sum(r['exact'] for r in results)}/{len(results)}")
    print(f"total: {total:.3f}s")
    if durations:
        print(f"avg/case: {sum(durations)/len(durations):.3f}s")
        print(f"median/case: {sorted(durations)[len(durations)//2]:.3f}s")
        print(f"min/case: {min(durations):.3f}s")
        print(f"max/case: {max(durations):.3f}s")
    print(f"total LLM calls: {len(calls)}")
    if call_durations:
        print(f"avg/LLM call: {sum(call_durations)/len(call_durations):.3f}s")
        print(f"max/LLM call: {max(call_durations):.3f}s")
    print("\n===== SLOWEST CASES =====")
    for r in slow:
        print(f"{r['seconds']:8.3f}s | calls={r['llm_calls']} | exact={r['exact']} | {r['text']}")
        for c in r["calls"]:
            print(f"           {c['stage']:10s} {c['seconds']:8.3f}s | system={c['system_chars']} chars | user={c['user_chars']} chars")

    out = Path("latency_profile_v47.json")
    out.write_text(json.dumps({
        "config": {
            "host": CONFIG.ollama_host,
            "model": CONFIG.model,
            "temperature": CONFIG.temperature,
            "max_output_tokens": CONFIG.max_output_tokens,
            "fast_mode": CONFIG.fast_mode,
            "repair_attempts": CONFIG.repair_attempts,
            "json_retry_attempts": CONFIG.json_retry_attempts,
        },
        "summary": {
            "cases": len(results),
            "exact": sum(r["exact"] for r in results),
            "total_seconds": total,
            "avg_case_seconds": sum(durations)/len(durations) if durations else 0,
            "median_case_seconds": sorted(durations)[len(durations)//2] if durations else 0,
            "max_case_seconds": max(durations) if durations else 0,
            "total_llm_calls": len(calls),
        },
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved detailed profile: {out.resolve()}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=106)
    args = ap.parse_args()
    profile(args.limit)
