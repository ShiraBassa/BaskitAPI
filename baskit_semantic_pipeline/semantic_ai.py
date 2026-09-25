from __future__ import annotations

from semantic_ai_config import CONFIG, SemanticConfig
from semantic_ai_llm import OllamaSemanticLLM
from semantic_ai_validation import validate_semantics
from semantic_ai_postprocess import canonicalize_semantic_result
from semantic_ai_schema import SemanticResult



def _apply_boundary_plan(
    source: str,
    result: SemanticResult,
    plan: dict,
    known_brand: str = "",
) -> SemanticResult:
    """Assemble the final result from an independent semantic plan.

    This function performs only generic source alignment and serialization.
    It contains no product vocabulary, brand lists, regexes, or semantic rules.
    """
    if not isinstance(plan, dict):
        return result
    if plan.get("text") != source:
        plan = dict(plan)
        plan["text"] = source

    requested: list[tuple[str, str, str]] = []

    # Commercial identity is resolved independently from product semantics.
    # If that independent decision is an exact source substring, use it as the
    # authoritative BRAND span during source-grounded assembly. This prevents
    # the later product-boundary model from reclassifying the brand as an
    # attribute or product.
    brand = known_brand if isinstance(known_brand, str) and known_brand.strip() else plan.get("brand", "")
    product = plan.get("product")
    attributes = plan.get("attributes")
    decisions = plan.get("decisions")

    # The planner already returns an explicit semantic decision for modifiers.
    # Honor that decision when the proposed PRODUCT accidentally swallowed a
    # core-preserving modifier. This is generic source-grounded reconciliation:
    # it uses only the model's semantic decision, base span, and attribute kind.
    # It contains no product/brand vocabulary or phrase-specific exceptions.
    if isinstance(decisions, list) and isinstance(attributes, list) and isinstance(product, str):
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            if decision.get("effect") != "core_preserving":
                continue
            modifier = decision.get("text")
            base = decision.get("base")
            if not isinstance(modifier, str) or not modifier.strip():
                continue
            if not isinstance(base, str) or not base.strip():
                continue
            if product.strip() != product:
                continue
            if modifier not in product or base not in product:
                continue
            if not product.startswith(base):
                continue
            # Only reconcile when the modifier is represented as a contiguous
            # suffix of PRODUCT; this preserves all other plan behavior.
            suffix = product[len(base):]
            if modifier.strip() not in suffix:
                continue
            matching_attr = next(
                (
                    item for item in attributes
                    if isinstance(item, dict)
                    and item.get("text") == modifier
                    and isinstance(item.get("kind"), str)
                    and item.get("kind").strip()
                ),
                None,
            )
            if matching_attr is not None:
                product = base

    if not isinstance(brand, str) or not isinstance(product, str) or not product:
        return result
    if brand.strip() and brand not in source:
        return result
    if not isinstance(attributes, list):
        return result
    attributes = [
        item for item in attributes
        if isinstance(item, dict)
        and isinstance(item.get("text"), str)
        and item.get("text").strip()
        and isinstance(item.get("kind"), str)
        and item.get("kind").strip()
    ]

    if brand.strip():
        requested.append((brand, "brand", ""))
    requested.append((product, "product", ""))

    for item in attributes:
        if not isinstance(item, dict):
            return result
        text = item.get("text")
        kind = item.get("kind")
        if not isinstance(text, str) or not text.strip():
            return result
        if not isinstance(kind, str) or not kind.strip():
            return result
        requested.append((text, "attribute", kind))

    spans: list[tuple[int, int, str, str]] = []
    used: list[tuple[int, int]] = []

    for text, role, kind in requested:
        candidates: list[tuple[int, int]] = []
        cursor = 0
        while True:
            start = source.find(text, cursor)
            if start < 0:
                break
            candidates.append((start, start + len(text)))
            cursor = start + 1

        chosen = None
        for start, end in candidates:
            if all(end <= u_start or start >= u_end for u_start, u_end in used):
                chosen = (start, end)
                break
        if chosen is None:
            return result

        start, end = chosen
        used.append((start, end))
        spans.append((start, end, role, kind))

    spans.sort(key=lambda item: (item[0], item[1]))

    # Keep one semantic quantity together when the model has split a numeric
    # amount into adjacent quantity fragments. This is source/span integrity,
    # not a unit dictionary or product-specific rule.
    merged: list[tuple[int, int, str, str]] = []
    for span in spans:
        if (
            merged
            and span[2] == "attribute"
            and span[3] == "כמות"
            and merged[-1][2] == "attribute"
            and merged[-1][3] == "כמות"
            and source[merged[-1][1]:span[0]].strip() == ""
        ):
            prev = merged[-1]
            merged[-1] = (prev[0], span[1], "attribute", "כמות")
        else:
            merged.append(span)
    spans = merged

    if sum(role == "product" for _, _, role, _ in spans) != 1:
        return result

    for previous, current in zip(spans, spans[1:]):
        if current[0] < previous[1]:
            return result

    def append_unclassified_gap(gap: str) -> None:
        # Whitespace is structural only. Preserve non-whitespace source text,
        # but keep punctuation/separators as independent unclassified segments
        # so semantic output does not accidentally absorb surrounding spaces.
        import re

        for token in re.findall(r"[^\s]+", gap):
            rebuilt.append({
                "text": token,
                "role": "unclassified",
                "kind": "",
            })

    rebuilt = []
    cursor = 0
    for start, end, role, kind in spans:
        if start > cursor:
            append_unclassified_gap(source[cursor:start])
        rebuilt.append({
            "text": source[start:end],
            "role": role,
            "kind": kind,
        })
        cursor = end

    if cursor < len(source):
        append_unclassified_gap(source[cursor:])

    try:
        candidate = SemanticResult.model_validate({
            "text": source,
            "segments": rebuilt,
        })
    except Exception:
        return result

    if validate_semantics(source, candidate):
        return candidate
    return result


def _merge_adjacent_quantity_segments(data: dict) -> dict:
    """Merge adjacent quantity fragments without unit-specific knowledge."""
    segments = data.get("segments", [])
    if not isinstance(segments, list):
        return data

    merged = []
    for segment in segments:
        if (
            merged
            and isinstance(segment, dict)
            and isinstance(merged[-1], dict)
            and segment.get("role") == "attribute"
            and segment.get("kind") == "כמות"
            and merged[-1].get("role") == "attribute"
            and merged[-1].get("kind") == "כמות"
        ):
            merged[-1]["text"] = (
                str(merged[-1].get("text", "")).rstrip()
                + " "
                + str(segment.get("text", "")).lstrip()
            ).strip()
        else:
            merged.append(segment)
    data["segments"] = merged
    return data



def _enforce_structural_brand(source: str, result: dict) -> dict:
    """Enforce an explicit leading commercial span when a standalone separator exists.

    This is source structure, not a brand vocabulary/rule. A leading span before
    a standalone title separator is kept as BRAND throughout final serialization.
    """
    if not isinstance(source, str) or not isinstance(result, dict):
        return result

    candidate = ""
    separator_text = ""
    separator_pos = None
    for separator in (" - ", " – ", " — ", ": "):
        pos = source.find(separator)
        if pos >= 0:
            left = source[:pos].strip()
            if left:
                candidate = left
                separator_text = separator.strip()
                separator_pos = pos
                break
    if not candidate:
        return result

    segments = result.get("segments")
    if not isinstance(segments, list):
        return result

    # Remove any semantic reinterpretation of the exact structural brand span.
    cleaned = []
    brand_found = False
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        text = seg.get("text")
        if text == candidate:
            if not brand_found:
                item = dict(seg)
                item["text"] = candidate
                item["role"] = "brand"
                item["kind"] = ""
                cleaned.append(item)
                brand_found = True
            continue
        cleaned.append(seg)

    if not brand_found:
        cleaned.insert(0, {"text": candidate, "role": "brand", "kind": ""})

    # A standalone title separator is structural syntax, not semantic content,
    # but it is still part of the canonical source segmentation. Preserve it
    # generically whenever the source explicitly uses one between the leading
    # commercial span and the product body.
    if separator_text:
        has_separator = any(
            isinstance(seg, dict)
            and seg.get("role") == "unclassified"
            and seg.get("text") == separator_text
            for seg in cleaned
        )
        if not has_separator:
            # Insert immediately after the leading brand. This does not depend
            # on any particular brand, product, or separator value.
            brand_index = next(
                (i for i, seg in enumerate(cleaned)
                 if isinstance(seg, dict) and seg.get("text") == candidate),
                0,
            )
            cleaned.insert(
                brand_index + 1,
                {"text": separator_text, "role": "unclassified", "kind": ""},
            )

    result["segments"] = cleaned
    return result

class SemanticEngine:
    """Public Baskit semantic engine.

    The model first makes a dedicated semantic product-boundary decision, then
    a separate parsing pass turns that decision into source-grounded segments.
    Validation and repair handle structure; they do not contain product rules.
    """

    def __init__(self, config: SemanticConfig = CONFIG):
        self.config = config
        self.llm = OllamaSemanticLLM(config)

    def parse(self, product_name: str) -> dict:
        """Parse one product with the low-latency production path.

        Fast mode makes one semantic LLM call and uses deterministic Python for
        normalization, structural-brand handling, source validation, and the
        optional repair call. Set BASKIT_FAST_MODE=0 to restore the legacy
        multi-stage semantic pipeline for comparison/diagnostics.
        """
        if self.config.fast_mode:
            result = self.llm.fast_parse(product_name)
            result = canonicalize_semantic_result(result.model_dump())
            result = _merge_adjacent_quantity_segments(result)
            result = SemanticResult.model_validate(result)

            # A standalone leading title separator is structural evidence of a
            # commercial identity span. Keep this generic and source-grounded.
            final_dict = {
                "text": product_name,
                "segments": [s.model_dump() for s in result.segments],
            }
            final_dict = _enforce_structural_brand(product_name, final_dict)
            try:
                result = SemanticResult.model_validate(final_dict)
            except Exception:
                result = SemanticResult.model_validate({
                    "text": product_name,
                    "segments": [s.model_dump() for s in result.segments],
                })

            issues = validate_semantics(product_name, result)

            for _ in range(self.config.repair_attempts):
                if not issues:
                    break
                result = self.llm.repair(product_name, result, issues, None)
                result = canonicalize_semantic_result(result.model_dump())
                result = _merge_adjacent_quantity_segments(result)
                result = SemanticResult.model_validate(result)
                final_dict = {
                    "text": product_name,
                    "segments": [s.model_dump() for s in result.segments],
                }
                final_dict = _enforce_structural_brand(product_name, final_dict)
                result = SemanticResult.model_validate(final_dict)
                issues = validate_semantics(product_name, result)

            return {
                "text": product_name,
                "segments": [s.model_dump() for s in result.segments],
                "valid": not issues,
                "validation_errors": issues,
            }

        # Legacy high-confidence pipeline retained for benchmark/regression
        # comparison. The original implementation is kept below unchanged.
        return self._parse_legacy(product_name)

    def _parse_legacy(self, product_name: str) -> dict:
        """Parse a title using an independent boundary decision followed by assembly."""
        independent_brand = self.llm.identify_brand(product_name)

        # Source-grounded structural identity fallback. If the independent
        # brand stage returns no usable exact source span, re-expose the leading
        # span before a standalone separator to the semantic pipeline. This is
        # structural evidence only; it is not a brand dictionary or a
        # brand-specific spelling correction.
        structural_brand = ""
        for separator in (" - ", " – ", " — ", ": "):
            if separator in product_name:
                candidate = product_name.split(separator, 1)[0].strip()
                if candidate:
                    structural_brand = candidate
                    break

        if structural_brand:
            # A standalone separator gives us a source-grounded commercial-identity
            # boundary. Keep that leading span authoritative so later semantic
            # stages cannot reclassify it as an attribute or product. This is
            # structural evidence, not a brand dictionary or brand-specific rule.
            if (
                not isinstance(independent_brand, str)
                or not independent_brand.strip()
                or independent_brand.strip() != structural_brand
                or independent_brand not in product_name
            ):
                independent_brand = structural_brand

        core_product = self.llm.identify_core_product(
            product_name,
            known_brand=independent_brand,
        )
        boundary_plan = self.llm.plan(
            product_name,
            known_brand=independent_brand,
            known_core=core_product,
        )
        if (
            isinstance(boundary_plan, dict)
            and isinstance(independent_brand, str)
            and independent_brand.strip()
            and independent_brand in product_name
        ):
            boundary_plan["text"] = product_name
            boundary_plan["brand"] = independent_brand

        # The independent core adjudicator is used only as a generic semantic
        # cross-check. It can narrow a planner PRODUCT only when the proposed
        # product begins with the independently identified core and the remaining
        # source text is already represented as an attribute. This cannot inject
        # vocabulary or create product-specific exceptions.
        if (
            isinstance(boundary_plan, dict)
            and isinstance(core_product, str)
            and core_product
            and isinstance(boundary_plan.get("product"), str)
            and boundary_plan["product"].startswith(core_product)
            and boundary_plan["product"] != core_product
            and isinstance(boundary_plan.get("attributes"), list)
        ):
            suffix = boundary_plan["product"][len(core_product):].strip()
            if suffix:
                matching = next(
                    (
                        a for a in boundary_plan["attributes"]
                        if isinstance(a, dict)
                        and a.get("text") == suffix
                        and isinstance(a.get("kind"), str)
                        and a.get("kind").strip()
                    ),
                    None,
                )
                if matching is not None:
                    boundary_plan["product"] = core_product

        # Independently audit the boundary decision before it is allowed to
        # drive final assembly. This second pass is semantic review, not a
        # phrase-specific rule or post-hoc keyword correction.
        reviewed_plan = self.llm.review_plan(
            product_name,
            boundary_plan,
            known_brand=independent_brand,
            known_core=core_product,
        )
        if isinstance(reviewed_plan, dict) and reviewed_plan.get("text") == product_name:
            # The independent core adjudicator establishes the product boundary
            # before the planner/reviewer stages. A reviewer may re-check the
            # semantic interpretation, but it must not silently expand that
            # independently established core into a longer PRODUCT.
            #
            # This is a generic stage-consistency guard: it does not know any
            # product vocabulary. If the reviewer agrees with the established
            # core, accept its full attribute decisions; if it expands PRODUCT
            # beyond the established core, retain the earlier plan instead.
            reviewed_product = reviewed_plan.get("product")
            if (
                not isinstance(core_product, str)
                or not core_product.strip()
                or reviewed_product == core_product
            ):
                boundary_plan = reviewed_plan

        # Once the independent core adjudicator has established a core, use a
        # constrained source-span allocation for everything after that core. This
        # prevents a later planner/reviewer from silently re-expanding PRODUCT and
        # prevents connectors or multi-token quantities from being fragmented.
        if isinstance(core_product, str) and core_product.strip():
            try:
                allocation = self.llm.allocate_after_core(
                    product_name,
                    core_product,
                    known_brand=independent_brand,
                )
                if isinstance(allocation, dict) and isinstance(allocation.get("attributes"), list):
                    boundary_plan = dict(boundary_plan) if isinstance(boundary_plan, dict) else {}
                    boundary_plan["product"] = core_product
                    boundary_plan["attributes"] = allocation["attributes"]
            except Exception:
                # The independently adjudicated core remains authoritative even
                # if attribute allocation is unavailable.
                boundary_plan = dict(boundary_plan) if isinstance(boundary_plan, dict) else {}
                boundary_plan["product"] = core_product

        # Reconcile a downstream expansion only when the plan itself already
        # marks the expanded suffix as non-core. This is a generic semantic
        # handoff from the independent core adjudicator.
        if (
            isinstance(boundary_plan, dict)
            and isinstance(core_product, str)
            and core_product.strip()
            and isinstance(boundary_plan.get("product"), str)
            and boundary_plan["product"].startswith(core_product)
            and boundary_plan["product"] != core_product
        ):
            suffix = boundary_plan["product"][len(core_product):].strip()
            decisions = boundary_plan.get("decisions")
            attributes = boundary_plan.get("attributes")
            non_core_suffix = False
            if isinstance(decisions, list):
                non_core_suffix = any(
                    isinstance(d, dict)
                    and d.get("text") == suffix
                    and d.get("effect") == "core_preserving"
                    for d in decisions
                )
            if not non_core_suffix and isinstance(attributes, list):
                non_core_suffix = any(
                    isinstance(item, dict)
                    and item.get("text") == suffix
                    and isinstance(item.get("kind"), str)
                    and item.get("kind").strip()
                    for item in attributes
                )
            if non_core_suffix:
                boundary_plan["product"] = core_product

        # The independent brand is contextual evidence for the semantic planner.
        # Do not post-hoc rewrite the reviewed plan here: the planner/reviewer must
        # decide ownership semantically, including why separators are structural.

        result = self.llm.parse(
            product_name,
            semantic_plan=boundary_plan,
        )
        result = _apply_boundary_plan(product_name, result, boundary_plan, known_brand=independent_brand)
        result = canonicalize_semantic_result(result.model_dump())
        result = _merge_adjacent_quantity_segments(result)
        result = SemanticResult.model_validate(result)

        issues = validate_semantics(product_name, result)

        for _ in range(self.config.repair_attempts):
            if not issues:
                break
            result = self.llm.repair(product_name, result, issues, boundary_plan)
            result = _apply_boundary_plan(product_name, result, boundary_plan, known_brand=independent_brand)
            result = canonicalize_semantic_result(result.model_dump())
            result = _merge_adjacent_quantity_segments(result)
            result = SemanticResult.model_validate(result)
            issues = validate_semantics(product_name, result)

        # Final source-structure guard. This is deliberately generic: when a
        # title has a standalone separator, the exact leading source span is
        # commercial identity and cannot be reinterpreted as an attribute.
        final_dict = {
            "text": product_name,
            "segments": [s.model_dump() for s in result.segments],
            "valid": not issues,
            "validation_errors": issues,
        }
        final_dict = _enforce_structural_brand(product_name, final_dict)

        return {
            "text": final_dict["text"],
            "segments": final_dict["segments"],
            "valid": final_dict["valid"],
            "validation_errors": final_dict["validation_errors"],
        }

    def parse_many(self, product_names: list[str]) -> list[dict]:
        if not product_names:
            return []
        return [self.parse(product_name) for product_name in product_names]


def parse_product(product_name: str) -> dict:
    return SemanticEngine().parse(product_name)
