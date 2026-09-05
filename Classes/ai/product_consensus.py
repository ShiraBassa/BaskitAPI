"""Consensus logic for source-grounded semantic product parsing."""

from __future__ import annotations

from collections import Counter

from .product_models import SemanticSegment
from .product_source import (
    normalize_spaces,
    source_intervals_touch,
)


ROLE_ORDER = (
    "product",
    "brand",
    "attribute",
    "unclassified",
)


def covering_segment(
    run: list[tuple[int, int, SemanticSegment]],
    start: int,
    end: int,
) -> SemanticSegment | None:
    """Return the model segment covering the complete source interval."""
    for segment_start, segment_end, segment in run:
        if segment_start <= start and end <= segment_end:
            return segment
    return None


def atomic_boundaries(
    source: str,
    valid_runs: list[list[tuple[int, int, SemanticSegment]]],
) -> list[tuple[int, int]]:
    """Build source atoms from the union of observed model boundaries."""
    boundaries = {0, len(source)}

    for run in valid_runs:
        for start, end, _ in run:
            boundaries.add(start)
            boundaries.add(end)

    ordered = sorted(boundaries)
    atoms: list[tuple[int, int]] = []

    for start, end in zip(ordered, ordered[1:]):
        if start == end:
            continue

        if normalize_spaces(source[start:end]) == "":
            continue

        atoms.append((start, end))

    return atoms


def _majority_role(
    observations: list[SemanticSegment],
    required: int,
) -> str:
    """Return the unique strict-majority role, or unclassified."""
    counts = Counter(
        observation.role
        for observation in observations
    )

    candidates = [
        role
        for role in ROLE_ORDER
        if counts.get(role, 0) >= required
    ]

    if len(candidates) == 1:
        return candidates[0]

    return "unclassified"


def select_attribute_kind(
    observations: list[SemanticSegment],
) -> str:
    """Select the consensus semantic kind supplied by the model."""
    kinds = [
        observation.kind
        for observation in observations
        if observation.role == "attribute" and observation.kind
    ]

    if not kinds:
        return ""

    counts = Counter(kinds)
    highest = max(counts.values())

    candidates = [
        kind
        for kind, count in counts.items()
        if count == highest
    ]

    return candidates[0]


def consensus_atomic_segments(
    source: str,
    valid_runs: list[list[tuple[int, int, SemanticSegment]]],
) -> list[tuple[int, int, str, str]]:
    """Produce source-grounded consensus across independently segmented runs.

    Every valid run already covers the complete source. A run may divide that
    source differently from another run. Each source atom therefore uses the
    segment that covers it rather than requiring identical model boundaries.
    """
    if not valid_runs:
        return []

    atoms: list[tuple[int, int, str, str]] = []
    required = len(valid_runs) // 2 + 1

    for start, end in atomic_boundaries(source, valid_runs):
        observations: list[SemanticSegment] = []

        for run in valid_runs:
            segment = covering_segment(run, start, end)
            if segment is not None:
                observations.append(segment)

        if len(observations) < required:
            atoms.append((start, end, "unclassified", ""))
            continue

        role = _majority_role(
            observations,
            required,
        )

        if role != "attribute":
            atoms.append((start, end, role, ""))
            continue

        kind = select_attribute_kind(observations)

        atoms.append((start, end, "attribute", kind))

    return merge_adjacent_atoms(source, atoms)


def merge_adjacent_atoms(
    source: str,
    atoms: list[tuple[int, int, str, str]],
) -> list[tuple[int, int, str, str]]:
    """Merge adjacent atoms with compatible semantic classifications."""
    if not atoms:
        return []

    merged: list[tuple[int, int, str, str]] = []

    for start, end, role, kind in atoms:
        if not merged:
            merged.append((start, end, role, kind))
            continue

        previous_start, previous_end, previous_role, previous_kind = merged[-1]

        same_role = previous_role == role
        same_kind = (
            role != "attribute"
            or previous_kind == kind
        )

        if (
            same_role
            and same_kind
            and source_intervals_touch(
                source,
                previous_end,
                start,
            )
        ):
            merged[-1] = (
                previous_start,
                end,
                role,
                kind,
            )
            continue

        merged.append((start, end, role, kind))

    return merged
