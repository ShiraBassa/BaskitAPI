from __future__ import annotations

from typing import Any


VALID_ROLES = {"brand", "product", "attribute", "unclassified"}


def canonicalize_semantic_result(data: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize schema representation without making semantic decisions.

    Every segment text is stripped of surrounding whitespace so whitespace is
    structural separation rather than part of any returned field. Semantic
    boundary/source validation is handled separately.
    """
    if not isinstance(data, dict):
        return {"text": "", "segments": []}

    original_text = str(data.get("text", ""))
    raw_segments = data.get("segments", [])
    if not isinstance(raw_segments, list):
        raw_segments = []

    segments: list[dict[str, str]] = []

    for raw in raw_segments:
        if not isinstance(raw, dict):
            continue

        role = raw.get("role")
        if role not in VALID_ROLES:
            legacy = raw.get("kind")
            role = legacy if legacy in VALID_ROLES else "unclassified"

        kind = str(raw.get("kind") or raw.get("attribute_kind") or "")
        if role != "attribute":
            kind = ""

        raw_text = str(raw.get("text", ""))
        text = raw_text.strip()

        segments.append({
            "text": text,
            "role": role,
            "kind": kind,
        })

    return {"text": original_text, "segments": segments}


def merge_relational_attribute_spans(data: dict[str, Any]) -> dict[str, Any]:
    """
    Compatibility hook.

    Semantic carrier decisions belong to the LLM's semantic reasoning.
    Python must not contain a dictionary of connector words or attempt to
    manufacture/merge semantic attributes from surface forms.
    """
    return data
