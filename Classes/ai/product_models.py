"""Data models for semantic supermarket product normalization."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SemanticSegment:
    """One source-grounded semantic segment returned by the model."""

    text: str
    role: str
    kind: str = ""


@dataclass
class ProductAttribute:
    """One normalized product attribute."""

    kind: str = ""
    value: str = ""

    @property
    def name(self) -> str:
        return self.kind


@dataclass
class ProductSemanticFields:
    """Final source-grounded semantic product fields."""

    raw_name: str = ""
    general_name: str = ""
    brand: str = ""
    attributes: list[ProductAttribute] = field(default_factory=list)

    @property
    def product_name(self) -> str:
        return self.general_name
