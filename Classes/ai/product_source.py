"""Source-text parsing, validation, and reconstruction helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .product_models import SemanticSegment


VALID_ROLES = frozenset(
    {"product", "brand", "attribute", "unclassified"}
)


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_source_char(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def parse_semantic_response(response: Any) -> list[Any] | None:
    if isinstance(response, dict):
        segments = response.get("segments")
    elif isinstance(response, str):
        try:
            decoded = json.loads(response)
        except json.JSONDecodeError:
            return None

        if not isinstance(decoded, dict):
            return None

        segments = decoded.get("segments")
    else:
        return None

    return segments if isinstance(segments, list) else None


def segment_source_spans(
    source: str,
    segments: list[SemanticSegment],
) -> list[tuple[int, int, SemanticSegment]] | None:
    """Align model segments to exact source spans without trusting model order."""
    source_len = len(source)
    spans: list[tuple[int, int, SemanticSegment]] = []

    def normalized_char(value: str) -> str:
        return normalize_source_char(value)

    def find_segment(start_at: int, text: str) -> tuple[int, int] | None:
        """Find the next complete source occurrence of text after start_at."""
        text = normalize_spaces(text)
        if not text:
            return None

        source_candidates = range(
            max(0, start_at),
            source_len,
        )

        for candidate_start in source_candidates:
            if source[candidate_start].isspace():
                continue

            text_index = 0
            source_index = candidate_start
            span_end: int | None = None

            while text_index < len(text):
                while text_index < len(text) and text[text_index].isspace():
                    text_index += 1

                while source_index < source_len and source[source_index].isspace():
                    source_index += 1

                if text_index >= len(text):
                    break

                if source_index >= source_len:
                    break

                if normalized_char(source[source_index]) != normalized_char(text[text_index]):
                    break

                source_index += 1
                text_index += 1
                span_end = source_index

            if text_index == len(text) and span_end is not None:
                return candidate_start, span_end

        return None

    for segment in segments:
        text = normalize_spaces(segment.text)
        if not text:
            return None

        found = find_segment(0, text)
        if found is None:
            return None

        start, end = found

        # A model segment must correspond to a unique, non-overlapping
        # occurrence in the source. If the first occurrence overlaps an
        # already-used span, search later occurrences.
        used = sorted(
            (existing_start, existing_end)
            for existing_start, existing_end, _ in spans
        )

        while any(
            start < existing_end and end > existing_start
            for existing_start, existing_end in used
        ):
            found = find_segment(end, text)
            if found is None:
                return None
            start, end = found

        spans.append((start, end, segment))

    spans.sort(key=lambda span: (span[0], span[1]))

    # Verify that the selected spans cover every non-whitespace source
    # character exactly once and preserve source order.
    position = 0
    for start, end, _ in spans:
        while position < source_len and source[position].isspace():
            position += 1

        if start != position:
            return None

        position = end

    while position < source_len and source[position].isspace():
        position += 1

    if position != source_len:
        return None

    return spans


def validate_segments(
    source: str,
    raw_segments: Any,
) -> list[tuple[int, int, SemanticSegment]] | None:
    if not isinstance(raw_segments, list) or not raw_segments:
        return None

    segments: list[SemanticSegment] = []

    for item in raw_segments:
        if not isinstance(item, dict):
            return None

        text = item.get("text")
        role = item.get("role")
        kind = item.get("kind", "")

        if not isinstance(text, str) or not text.strip():
            return None

        if not isinstance(role, str) or role not in VALID_ROLES:
            return None

        if kind is None:
            kind = ""
        elif not isinstance(kind, str):
            return None

        text = normalize_spaces(text)
        kind = normalize_spaces(kind)

        if role != "attribute":
            kind = ""

        segments.append(
            SemanticSegment(
                text=text,
                role=role,
                kind=kind,
            )
        )

    return segment_source_spans(source, segments)


def contains_whole_phrase(container: str, phrase: str) -> bool:
    container = normalize_spaces(container)
    phrase = normalize_spaces(phrase)

    if not phrase:
        return False

    haystack = container.casefold()
    needle = phrase.casefold()
    start = haystack.find(needle)

    while start >= 0:
        end = start + len(needle)

        left_ok = start == 0 or not (
            haystack[start - 1].isalnum() and needle[0].isalnum()
        )
        right_ok = end == len(haystack) or not (
            haystack[end].isalnum() and needle[-1].isalnum()
        )

        if left_ok and right_ok:
            return True

        start = haystack.find(needle, start + 1)

    return False


def source_intervals_touch(
    source: str,
    previous_end: int,
    next_start: int,
) -> bool:
    return (
        previous_end <= next_start
        and normalize_spaces(source[previous_end:next_start]) == ""
    )


def reconstruct_source_ranges(
    source: str,
    ranges: list[tuple[int, int]],
) -> str:
    if not ranges:
        return ""

    keep = [False] * len(source)

    for start, end in ranges:
        start = max(0, start)
        end = min(len(source), end)

        for index in range(start, end):
            keep[index] = True

    return normalize_spaces(
        "".join(
            source[index]
            for index, include in enumerate(keep)
            if include
        )
    )
