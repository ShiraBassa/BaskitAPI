from __future__ import annotations

from semantic_ai_schema import SemanticResult


class ValidationIssue(ValueError):
    pass


def _find_all_non_overlapping_occurrences(source: str, text: str) -> list[tuple[int, int]]:
    out = []
    if not text:
        return out
    start = 0
    while True:
        i = source.find(text, start)
        if i < 0:
            return out
        out.append((i, i + len(text)))
        start = i + len(text)


def validate_semantics(source: str, result: SemanticResult) -> list[str]:
    issues: list[str] = []

    if not source.strip():
        issues.append("source text is empty")
        return issues

    products = [s for s in result.segments if s.role == "product"]
    if not result.segments:
        issues.append("result must contain at least one segment")
    if len(products) != 1:
        issues.append(f"expected exactly one product segment, got {len(products)}")

    for idx, seg in enumerate(result.segments):
        if seg.role != "attribute" and seg.kind:
            issues.append(
                f"segment {idx} has kind={seg.kind!r} but role={seg.role!r}; "
                "kind must be empty for non-attributes"
            )

        if seg.role == "attribute":
            kind = seg.kind.strip()
            if not kind:
                issues.append(f"segment {idx} attribute kind is empty")
            elif kind.lower() in {"undefined", "unknown", "null"}:
                issues.append(f"segment {idx} attribute kind {seg.kind!r} is not allowed")
            elif not any("\u0590" <= char <= "\u05FF" for char in kind):
                issues.append(f"segment {idx} attribute kind {seg.kind!r} must be Hebrew")
            elif any("A" <= char <= "Z" or "a" <= char <= "z" for char in kind):
                issues.append(f"segment {idx} attribute kind {seg.kind!r} must not contain English letters")

        if seg.role == "unclassified" and seg.text.strip() in {"-", "–", "—"}:
            if not seg.text.strip():
                issues.append(f"segment {idx} separator text is empty")

        occurrences = _find_all_non_overlapping_occurrences(source, seg.text)
        if not occurrences:
            issues.append(
                f"segment {idx} text {seg.text!r} does not occur directly in source"
            )

    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for idx, seg in enumerate(result.segments):
        pos = source.find(seg.text, cursor)
        if pos < 0:
            if seg.text in source:
                issues.append(f"segment {idx} text {seg.text!r} appears out of order in source")
            continue
        spans.append((pos, pos + len(seg.text), idx))
        cursor = pos + len(seg.text)

    for (a0, a1, ai), (b0, b1, bi) in zip(spans, spans[1:]):
        if b0 < a1:
            issues.append(f"segments {ai} and {bi} overlap")

    return issues


def assert_valid(source: str, result: SemanticResult) -> None:
    issues = validate_semantics(source, result)
    if issues:
        raise ValidationIssue("; ".join(issues))