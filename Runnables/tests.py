import json
from pathlib import Path

RESULTS_FILE = Path(__file__).resolve().parent.parent / "baskit_semantic_pipeline" / "benchmark_results.jsonl"


def print_segment(segment):
    role = segment.get("role", "")
    kind = segment.get("kind", "")
    text = segment.get("text", "")

    if role == "product":
        label = "PRODUCT"
    elif role == "brand":
        label = "BRAND"
    elif role == "attribute":
        label = f"ATTRIBUTE · {kind}" if kind else "ATTRIBUTE"
    else:
        label = role.upper() if role else "UNCLASSIFIED"

    print(f"    {label:<28} {text}")


def print_result(result):
    print("\n" + "═" * 90)
    print(f"  #{result['line']}  {result['text']}")
    print("═" * 90)

    prediction = result["prediction"]
    gold = result["gold"]

    print("\n  PREDICTION")
    print("  ──────────")
    for segment in prediction.get("segments", []):
        print_segment(segment)

    print("\n  GOLD")
    print("  ────")
    for segment in gold.get("segments", []):
        print_segment(segment)

    print("\n  STATUS")
    print(f"    {'✓ EXACT MATCH' if result.get('passed') else '✗ DIFFERENT'}")

    if prediction.get("validation_errors"):
        print("\n  VALIDATION ERRORS")
        for error in prediction["validation_errors"]:
            print(f"    • {error}")


def main():
    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        results = [json.loads(line) for line in f if line.strip()]

    for result in results:
        print_result(result)

    passed = sum(1 for result in results if result.get("passed"))
    total = len(results)

    print("\n" + "═" * 90)
    print(f"  SUMMARY: {passed}/{total} exact semantic matches ({passed / total * 100:.2f}%)")
    print("═" * 90)


if __name__ == "__main__":
    main()