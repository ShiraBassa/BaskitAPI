"""Public semantic supermarket product normalizer for Baskit."""

from __future__ import annotations

import json

from typing import Any

from .ollama_client import OllamaClient
from .product_consensus import consensus_atomic_segments
from .product_models import ProductAttribute, ProductSemanticFields, SemanticSegment
from .product_prompt import semantic_prompt, semantic_schema
from .product_source import (
    contains_whole_phrase,
    normalize_source_char,
    normalize_spaces,
    parse_semantic_response,
    reconstruct_source_ranges,
    segment_source_spans,
    source_intervals_touch,
    validate_segments,
)


class ProductNormalizer:
    """Normalize supermarket product names using three-run semantic consensus."""

    CONSENSUS_RUNS = 3
    VALID_ROLES = frozenset(
        {"product", "brand", "attribute", "unclassified"}
    )

    def __init__(self, ollama_client: OllamaClient | None = None):
        self.ollama_client = ollama_client or OllamaClient()
        self.model = self.ollama_client.model

    # ------------------------------------------------------------------
    # Compatibility/static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_spaces(value: str) -> str:
        return normalize_spaces(value)

    @staticmethod
    def _normalize_source_char(value: str) -> str:
        return normalize_source_char(value)


    @classmethod
    def _contains_whole_phrase(
        cls,
        container: str,
        phrase: str,
    ) -> bool:
        return contains_whole_phrase(container, phrase)

    @staticmethod
    def _parse_object(response: Any) -> dict[str, Any]:
        import json

        if isinstance(response, dict):
            data = response
        elif isinstance(response, str):
            data = json.loads(response)
        else:
            raise ValueError(
                "Normalizer response must be a JSON object"
            )

        if not isinstance(data, dict):
            raise ValueError(
                "Normalizer response must be a JSON object"
            )

        return data

    @classmethod
    def _normalize_semantic_response(
        cls,
        response: Any,
    ) -> list[Any] | None:
        return parse_semantic_response(response)

    # ------------------------------------------------------------------
    # Schema / prompt compatibility
    # ------------------------------------------------------------------

    @classmethod
    def _semantic_schema(cls) -> dict[str, Any]:
        return semantic_schema()

    def build_semantic_prompt(
        self,
        product_name: str,
        run_number: int = 1,
    ) -> str:
        return semantic_prompt(
            product_name,
            run_number,
        )

    # ------------------------------------------------------------------
    # Source validation compatibility
    # ------------------------------------------------------------------

    @classmethod
    def _segment_source_spans(
        cls,
        source: str,
        segments: list[SemanticSegment],
    ) -> list[tuple[int, int, SemanticSegment]] | None:
        return segment_source_spans(
            source,
            segments,
        )

    @classmethod
    def _validate_segments(
        cls,
        source: str,
        raw_segments: Any,
    ) -> list[tuple[int, int, SemanticSegment]] | None:
        return validate_segments(
            source,
            raw_segments,
        )

    # ------------------------------------------------------------------
    # Model request
    # ------------------------------------------------------------------

    def _request_semantic_once(
        self,
        product_name: str,
        run_number: int,
    ) -> list[tuple[int, int, SemanticSegment]] | None:
        payload = self.ollama_client.payload(
            system=(
                "You are Baskit's semantic supermarket-product parser. "
                "Understand the complete source phrase. "
                "Use the source language for semantic metadata. "
                "Preserve source text exactly and classify its semantic role."
            ),
            user=self.build_semantic_prompt(
                product_name,
                run_number,
            ),
            schema=self._semantic_schema(),
            num_predict=256,
        )

        payload.setdefault("options", {})["temperature"] = 0

        response, raw = self.ollama_client.chat(payload)

        segments = self._normalize_semantic_response(response)

        if segments is None and isinstance(raw, str) and raw.strip():
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                decoded = None
            segments = self._normalize_semantic_response(decoded)

        if segments is None:
            return None

        return self._validate_segments(
            product_name,
            segments,
        )

    # ------------------------------------------------------------------
    # Consensus compatibility
    # ------------------------------------------------------------------

    @classmethod
    def _atomic_boundaries(
        cls,
        source: str,
        valid_runs: list[list[tuple[int, int, SemanticSegment]]],
    ) -> list[tuple[int, int]]:
        from .product_consensus import atomic_boundaries

        return atomic_boundaries(source, valid_runs)

    @staticmethod
    def _covering_segment(
        run: list[tuple[int, int, SemanticSegment]],
        start: int,
        end: int,
    ) -> SemanticSegment | None:
        from .product_consensus import covering_segment

        return covering_segment(run, start, end)

    @classmethod
    def _consensus_atomic_segments(
        cls,
        source: str,
        valid_runs: list[list[tuple[int, int, SemanticSegment]]],
    ) -> list[tuple[int, int, str, str]]:
        return consensus_atomic_segments(
            source,
            valid_runs,
        )

    @classmethod
    def _source_intervals_touch(
        cls,
        source: str,
        previous_end: int,
        next_start: int,
    ) -> bool:
        return source_intervals_touch(
            source,
            previous_end,
            next_start,
        )

    @classmethod
    def _reconstruct_source_ranges(
        cls,
        source: str,
        ranges: list[tuple[int, int]],
    ) -> str:
        return reconstruct_source_ranges(
            source,
            ranges,
        )

    # ------------------------------------------------------------------
    # Result construction
    # ------------------------------------------------------------------

    @classmethod
    def _build_result(
        cls,
        source: str,
        atoms: list[tuple[int, int, str, str]],
    ) -> ProductSemanticFields | None:
        if not any(role == "product" for _, _, role, _ in atoms):
            return None

        general_name = cls._reconstruct_source_ranges(
            source,
            [
                (start, end)
                for start, end, role, _ in atoms
                if role == "product"
            ],
        )
        if not general_name:
            return None

        brand_groups: list[tuple[int, int]] = []
        current_start: int | None = None
        current_end: int | None = None

        for start, end, role, _ in atoms:
            if role != "brand":
                if current_start is not None and current_end is not None:
                    brand_groups.append((current_start, current_end))
                current_start = None
                current_end = None
                continue

            if (
                current_start is not None
                and current_end is not None
                and cls._source_intervals_touch(source, current_end, start)
            ):
                current_end = end
            else:
                if current_start is not None and current_end is not None:
                    brand_groups.append((current_start, current_end))
                current_start = start
                current_end = end

        if current_start is not None and current_end is not None:
            brand_groups.append((current_start, current_end))

        brand = ""
        if brand_groups:
            start, end = max(
                brand_groups,
                key=lambda interval: interval[1] - interval[0],
            )
            brand = cls._normalize_spaces(source[start:end])

        attributes: list[ProductAttribute] = []
        current_kind: str | None = None
        current_start: int | None = None
        current_end: int | None = None

        def flush_attribute() -> None:
            nonlocal current_kind, current_start, current_end
            if current_start is None or current_end is None:
                current_kind = None
                current_start = None
                current_end = None
                return

            value = cls._normalize_spaces(source[current_start:current_end])
            if value and current_kind:
                attributes.append(
                    ProductAttribute(
                        kind=current_kind,
                        value=value,
                    )
                )

            current_kind = None
            current_start = None
            current_end = None

        for start, end, role, kind in atoms:
            if role != "attribute":
                flush_attribute()
                continue

            if not kind:
                flush_attribute()
                continue

            if (
                current_start is not None
                and current_end is not None
                and current_kind == kind
                and cls._source_intervals_touch(source, current_end, start)
            ):
                current_end = end
            else:
                flush_attribute()
                current_kind = kind
                current_start = start
                current_end = end

        flush_attribute()

        return ProductSemanticFields(
            raw_name=source,
            general_name=general_name,
            brand=brand,
            attributes=attributes,
        )

    # ------------------------------------------------------------------
    # Main normalization
    # ------------------------------------------------------------------

    def normalize(
        self,
        product_name: str,
    ) -> ProductSemanticFields:
        if (
            not isinstance(product_name, str)
            or not product_name.strip()
        ):
            raise ValueError(
                "Product name must be a non-empty string"
            )

        source = self._normalize_spaces(
            product_name
        )

        runs: list[
            list[tuple[int, int, SemanticSegment]]
        ] = []

        for run_number in range(
            1,
            self.CONSENSUS_RUNS + 1,
        ):
            run = self._request_semantic_once(
                source,
                run_number,
            )

            if run is not None:
                runs.append(run)

        if not runs:
            return ProductSemanticFields(
                raw_name=source,
                general_name=source,
                brand="",
                attributes=[],
            )

        atoms = self._consensus_atomic_segments(source, runs)
        result = self._build_result(source, atoms)

        if result is not None:
            return result

        return ProductSemanticFields(
            raw_name=source,
            general_name=source,
            brand="",
            attributes=[],
        )

    # ------------------------------------------------------------------
    # Compatibility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _general_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "general_name": {
                    "type": "string",
                },
            },
            "required": ["general_name"],
            "additionalProperties": False,
        }

    def _request_general(
        self,
        product_name: str,
    ) -> str:
        raise RuntimeError(
            "General-name extraction is intentionally "
            "not a separate model operation"
        )

    def _request_brand(
        self,
        product_name: str,
    ) -> str:
        run = self._request_semantic_once(
            product_name,
            1,
        )

        if not run:
            return ""

        source = self._normalize_spaces(
            product_name
        )

        groups: list[tuple[int, int]] = []
        current_start: int | None = None
        current_end: int | None = None

        for start, end, segment in run:
            if segment.role != "brand":
                if (
                    current_start is not None
                    and current_end is not None
                ):
                    groups.append(
                        (current_start, current_end)
                    )

                current_start = None
                current_end = None
                continue

            if (
                current_start is not None
                and current_end is not None
                and self._source_intervals_touch(
                    source,
                    current_end,
                    start,
                )
            ):
                current_end = end
            else:
                if (
                    current_start is not None
                    and current_end is not None
                ):
                    groups.append(
                        (current_start, current_end)
                    )

                current_start = start
                current_end = end

        if (
            current_start is not None
            and current_end is not None
        ):
            groups.append(
                (current_start, current_end)
            )

        if groups:
            start, end = max(
                groups,
                key=lambda interval: (
                    interval[1] - interval[0]
                ),
            )
            return self._normalize_spaces(
                source[start:end]
            )

        return ""

    def _request_attributes(
        self,
        product_name: str,
    ) -> list[ProductAttribute]:
        run = self._request_semantic_once(
            product_name,
            1,
        )

        if not run:
            return []

        source = self._normalize_spaces(
            product_name
        )

        attributes: list[ProductAttribute] = []

        current_kind: str | None = None
        current_start: int | None = None
        current_end: int | None = None

        def flush() -> None:
            nonlocal current_kind
            nonlocal current_start
            nonlocal current_end

            if (
                current_start is not None
                and current_end is not None
                and current_kind
            ):
                value = self._normalize_spaces(
                    source[
                        current_start:current_end
                    ]
                )

                if value:
                    attributes.append(
                        ProductAttribute(
                            kind=current_kind,
                            value=value,
                        )
                    )

            current_kind = None
            current_start = None
            current_end = None

        for start, end, segment in run:
            if segment.role != "attribute":
                flush()
                continue

            if (
                current_start is not None
                and current_end is not None
                and segment.kind == current_kind
                and self._source_intervals_touch(
                    source,
                    current_end,
                    start,
                )
            ):
                current_end = end
            else:
                flush()
                current_kind = segment.kind
                current_start = start
                current_end = end

        flush()
        return attributes

    def build_general_name_prompt(
        self,
        product_name: str,
    ) -> str:
        return f"""You are Baskit's supermarket product identity engine.

SOURCE PRODUCT:
{product_name}

Determine the broad natural supermarket shopping-list identity of the product.

Use natural terminology in the same language as the source.
For Hebrew input, use natural Hebrew.

Return JSON only:
{{"general_name":"..."}}
"""

    def build_general_verification_prompt(
        self,
        product_name: str,
        candidate: str,
        brand: str,
        attributes: list[ProductAttribute],
    ) -> str:
        return self.build_general_name_prompt(
            product_name
        )

    @classmethod
    def _validated_general(
        cls,
        product_name: str,
        value: str,
    ) -> str:
        value = cls._normalize_spaces(value)

        if not value:
            return ""

        if not cls._contains_whole_phrase(
            product_name,
            value,
        ):
            return ""

        return value

    @classmethod
    def _is_valid_brand(
        cls,
        product_name: str,
        brand: str,
    ) -> bool:
        brand = cls._normalize_spaces(brand)

        if not brand:
            return True

        return cls._contains_whole_phrase(
            product_name,
            brand,
        )

    @staticmethod
    def remove_brand(
        product_name: str,
        brand: str,
    ) -> str:
        source = ProductNormalizer._normalize_spaces(
            product_name
        )

        brand = ProductNormalizer._normalize_spaces(
            brand
        )

        if not brand:
            return source

        start = source.casefold().find(
            brand.casefold()
        )

        if start < 0:
            return source

        end = start + len(brand)

        return ProductNormalizer._normalize_spaces(
            source[:start]
            + " "
            + source[end:]
        )

    @classmethod
    def _is_result_usable(
        cls,
        product_name: str,
        fields: ProductSemanticFields,
    ) -> bool:
        if not fields.general_name:
            return False

        if (
            fields.brand
            and not cls._contains_whole_phrase(
                product_name,
                fields.brand,
            )
        ):
            return False

        return all(
            attribute.kind
            and attribute.value
            and cls._contains_whole_phrase(
                product_name,
                attribute.value,
            )
            for attribute in fields.attributes
        )


__all__ = [
    "ProductNormalizer",
    "ProductAttribute",
    "ProductSemanticFields",
]
