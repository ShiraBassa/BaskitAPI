from __future__ import annotations

import json
from pathlib import Path


def _examples_path(custom_path: str | Path | None = None) -> Path:
    if custom_path:
        return Path(custom_path)
    return Path(__file__).resolve().parent / "baskit_training_examples_hebrew_v1.jsonl"


_EXAMPLE_RECORDS: list[tuple[str, list[dict[str, str]]]] | None = None

_VALID_ROLES = {
    "product",
    "brand",
    "attribute",
    "unclassified",
}


def _record_to_segments(record: dict) -> list[dict[str, str]] | None:
    segments = record.get("segments")

    if not isinstance(segments, list) or not segments:
        return None

    valid_segments: list[dict[str, str]] = []

    for segment in segments:
        if not isinstance(segment, dict):
            return None

        text = segment.get("text")
        role = segment.get("role")
        kind = segment.get("kind", "")

        if not isinstance(text, str) or not text.strip():
            return None

        if role not in _VALID_ROLES:
            return None

        if not isinstance(kind, str):
            return None

        valid_segments.append(
            {
                "text": text,
                "role": role,
                "kind": kind,
            }
        )

    return valid_segments or None


def _example_signature(segments: list[dict[str, str]]) -> frozenset[str]:
    return frozenset(
        f"{segment['role']}:{segment['kind']}"
        for segment in segments
        if segment["role"] in {"brand", "attribute"}
        and segment["kind"]
    )


def _example_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in text.split()
        if token.strip()
    )


def _example_quality(
    text: str,
    segments: list[dict[str, str]],
    target_tokens: frozenset[str],
    target_word_count: int,
) -> tuple[int, int, int, int, int, int]:
    example_tokens = _example_tokens(text)
    lexical_overlap = len(example_tokens & target_tokens)

    example_segment_count = len(segments)
    segment_count_distance = abs(example_segment_count - target_word_count)

    signature = _example_signature(segments)
    semantic_count = len(signature)
    attribute_count = sum(
        1 for segment in segments if segment["role"] == "attribute"
    )
    product_count = sum(
        1 for segment in segments if segment["role"] == "product"
    )

    return (
        lexical_overlap,
        semantic_count,
        attribute_count,
        product_count,
        -segment_count_distance,
        -len(text),
    )


def _load_examples(custom_path: str | Path | None = None) -> list[tuple[str, list[dict[str, str]]]]:
    global _EXAMPLE_RECORDS

    if _EXAMPLE_RECORDS is not None and custom_path is None:
        return _EXAMPLE_RECORDS

    path = _examples_path(custom_path)
    if not path.exists():
        if custom_path is None:
            _EXAMPLE_RECORDS = []
            return _EXAMPLE_RECORDS
        return []

    loaded: list[tuple[str, list[dict[str, str]]]] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not isinstance(record, dict):
            continue

        text = record.get("text")
        segments = _record_to_segments(record)

        if not isinstance(text, str) or not text.strip() or not segments:
            prompt = record.get("prompt")
            completion = record.get("completion")

            if not isinstance(prompt, str) or not isinstance(completion, str):
                continue

            marker = "Product name:"
            if marker not in prompt:
                continue

            text = prompt.rsplit(marker, 1)[1].strip()
            if not text:
                continue

            try:
                completion_record = json.loads(completion)
            except json.JSONDecodeError:
                continue

            if not isinstance(completion_record, dict):
                continue

            segments = _record_to_segments(completion_record)

        if not isinstance(text, str) or not text.strip() or not segments:
            continue

        loaded.append((text, segments))

    if custom_path is None:
        _EXAMPLE_RECORDS = loaded
    return loaded


def build_few_shot_messages(
    max_examples: int,
    target_text: str | None = None,
    examples_path: str | Path | None = None,
) -> list[dict[str, str]]:
    if max_examples <= 0:
        return []

    loaded_records = _load_examples(examples_path)
    examples = []
    for text, segments in loaded_records:
        signature = _example_signature(segments)
        tokens = _example_tokens(text)
        attribute_count = sum(
            1 for segment in segments if segment["role"] == "attribute"
        )
        product_count = sum(
            1 for segment in segments if segment["role"] == "product"
        )
        examples.append(
            (
                signature,
                text,
                segments,
                tokens,
                len(segments),
                attribute_count,
                product_count,
            )
        )

    if not examples:
        return []

    if target_text:
        target_tokens = _example_tokens(target_text)
        target_word_count = len(target_text.split())

        ranked = sorted(
            examples,
            key=lambda example: _example_quality(
                example[1],
                example[2],
                target_tokens,
                target_word_count,
            ),
            reverse=True,
        )
        selected = ranked[:max_examples]
    else:
        selected = examples[:max_examples]

    messages: list[dict[str, str]] = []

    for _, text, segments, _, _, _, _ in selected:
        messages.append(
            {
                "role": "user",
                "content": (
                    "Parse this supermarket product name.\n\n"
                    f"Product name: {text}"
                ),
            }
        )

        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(
                    {"segments": segments},
                    ensure_ascii=False,
                ),
            }
        )

    return messages