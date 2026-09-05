import argparse
import json
import sys

from semantic_ai import SemanticEngine


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("product_name")
    args = parser.parse_args()

    try:
        result = SemanticEngine().parse(args.product_name)
    except Exception as exc:
        print(f"Semantic engine error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
