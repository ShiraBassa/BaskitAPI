from __future__ import annotations

from semantic_ai_schema import SemanticResult


VALID_KINDS = {
    "כמות", "מספר יחידות", "אחוז שומן", "טעם", "ריח",
    "צבע", "חומר", "גודל", "מידה", "קהל יעד", "צורה", "סוג",
}


class ValidationIssue(ValueError):
    pass


def validate_semantics(source: str, result: SemanticResult) -> list[str]:
    """Validate structure and source coverage without semantic hard-coding."""
    issues: list[str] = []

    if not isinstance(source, str) or not source.strip():
        return ["source text is empty"]

    if result.text != source:
        issues.append("result.text does not exactly equal source text")

    if not result.segments:
        issues.append("result must contain at least one segment")
        return issues

    products = [s for s in result.segments if s.role == "product"]
    if len(products) != 1:
        issues.append(f"expected exactly one product segment, got {len(products)}")

    cursor = 0

    for idx, seg in enumerate(result.segments):
        text = seg.text.strip()

        if not text:
            issues.append(f"segment {idx} text is empty")
            continue

        # Semantic output may intentionally omit purely grammatical/relational
        # carrier words. Therefore a segment does not have to begin immediately
        # after the previous segment. It must, however, be an exact source
        # substring appearing after the previous segment, preserving order.
        pos = source.find(text, cursor)
        if pos < 0:
            issues.append(
                f"segment {idx} text is not an exact source substring after "
                f"the previous segment"
            )
        else:
            end_pos = pos + len(text)

            # A semantic segment must not end halfway through a source token.
            # This is especially important for measurements/units, where a
            # model can otherwise return a valid substring that silently drops
            # the remainder of the unit. This is generic source integrity, not
            # a unit dictionary or product-specific rule.
            if end_pos < len(source) and not source[end_pos].isspace():
                issues.append(
                    f"segment {idx} ends inside a source token; "
                    "the complete contiguous source token must be preserved"
                )

            cursor = end_pos

        if seg.role != "attribute":
            if seg.kind:
                issues.append(
                    f"segment {idx} has kind={seg.kind!r} but role={seg.role!r}; "
                    "kind must be empty for non-attributes"
                )
        else:
            kind = seg.kind.strip()
            if not kind:
                issues.append(f"segment {idx} attribute kind is empty")
            elif kind not in VALID_KINDS:
                issues.append(
                    f"segment {idx} attribute kind {kind!r} is not in the taxonomy"
                )

    # Gaps are permitted only because the semantic representation may omit
    # semantically empty relational carriers. The LLM is responsible for deciding
    # whether a gap is genuinely empty; validation checks source grounding/order,
    # not vocabulary-specific semantics.

    return issues


def assert_valid(source: str, result: SemanticResult) -> None:
    issues = validate_semantics(source, result)
    if issues:
        raise ValidationIssue("; ".join(issues))
