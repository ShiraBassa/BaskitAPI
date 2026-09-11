from __future__ import annotations

import json
import math
from collections import Counter
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


def _token_idf_weights(
    all_texts: list[str],
) -> dict[str, float]:
    """
    Inverse-document-frequency weight per token across the training pool.

    Plain lexical overlap treats every shared word equally, so a target and
    an example that only share common nouns/units/numbers (e.g. "200",
    "גרם") outrank a pair that shares the one rare word that actually
    signals the correct segmentation pattern (e.g. "ללא", "בניחוח"). IDF
    weighting fixes this: common tokens shared by many examples contribute
    little to the score, rare tokens shared by few contribute a lot.
    """
    doc_freq: Counter[str] = Counter()
    total_docs = 0

    for text in all_texts:
        total_docs += 1
        for token in _example_tokens(text):
            doc_freq[token] += 1

    return {
        token: math.log((total_docs + 1) / (freq + 1)) + 1.0
        for token, freq in doc_freq.items()
    }



def _semantic_cue_score(
    target_text: str,
    example_text: str,
    example_segments: list[dict[str, str]],
) -> float:
    """Prefer examples that teach the same semantic construction."""
    t = target_text.casefold()
    e = example_text.casefold()
    signature = _example_signature(example_segments)
    score = 0.0

    for cue, kind, weight in [
        ("בניחוח", "ריח", 4.0),
        ("בריח", "ריח", 4.0),
        ("בטעם", "טעם", 4.0),
        ("עם ", "טעם", 3.0),
        ("לנשים", "קהל יעד", 3.0),
        ("לגברים", "קהל יעד", 3.0),
        ("לילדים", "קהל יעד", 3.0),
        ("לתינוק", "קהל יעד", 3.0),
        ("לכלבים", "קהל יעד", 3.0),
        ("לחתולים", "קהל יעד", 3.0),
        ("%", "אחוז שומן", 3.0),
        ("בשמן", "סוג", 5.0),
        ("פרוס", "סוג", 5.0),
        ("קפוא", "סוג", 5.0),
        ("ללא ", "סוג", 3.0),
    ]:
        if cue in t and cue in e and f"attribute:{kind}" in signature:
            score += weight
    return score

def _example_quality(
    text: str,
    segments: list[dict[str, str]],
    target_text: str,
    target_tokens: frozenset[str],
    target_word_count: int,
    idf: dict[str, float],
) -> tuple[float, float, int, int, int, int, int]:
    example_tokens = _example_tokens(text)
    shared_tokens = example_tokens & target_tokens
    lexical_overlap = sum(idf.get(token, 1.0) for token in shared_tokens)

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
        _semantic_cue_score(target_text, text, segments),
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



def load_example_texts(custom_path: str | Path | None = None) -> set[str]:
    """Return the source texts represented by an examples JSONL file.

    This helper is used by the benchmark to prevent exact held-out/check
    products from leaking into few-shot examples.
    """
    return {text for text, _ in _load_examples(custom_path)}


def build_few_shot_messages(
    max_examples: int,
    target_text: str | None = None,
    examples_path: str | Path | None = None,
    excluded_texts: set[str] | None = None,
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

    excluded = set(excluded_texts or set())
    if target_text:
        excluded.add(target_text)

    if target_text:
        target_tokens = _example_tokens(target_text)
        target_word_count = len(target_text.split())
        idf = _token_idf_weights([text for text, _ in loaded_records])

        ranked = sorted(
            examples,
            key=lambda example: _example_quality(
                example[1],
                example[2],
                target_text,
                target_tokens,
                target_word_count,
                idf,
            ),
            reverse=True,
        )

        selected: list[tuple] = []
        selected_texts: set[str] = set()

        for candidate in ranked:
            if len(selected) >= max_examples:
                break
            if candidate[1] in selected_texts or candidate[1] in excluded:
                continue
            selected.append(candidate)
            selected_texts.add(candidate[1])

        selected = selected[:max_examples]
    else:
        selected = [
            example for example in examples
            if example[1] not in excluded
        ][:max_examples]

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