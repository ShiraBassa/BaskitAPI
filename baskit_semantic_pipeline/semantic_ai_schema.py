from typing import Literal
from pydantic import BaseModel, ConfigDict


Role = Literal["product", "brand", "attribute", "unclassified"]


class Segment(BaseModel):
    """
    Shape-only validation.

    Content-level correctness (blank text, kind formatting, Hebrew-only
    kind, role/kind consistency, source coverage) is intentionally NOT
    enforced here. Those checks live in semantic_ai_validation.py, whose
    output feeds the repair loop. If we raise here instead, a recoverable
    mistake (e.g. an English word in `kind`) crashes the whole parse
    before repair ever gets a chance to run.
    """

    model_config = ConfigDict(extra="forbid")

    text: str
    role: Role
    kind: str = ""


class SemanticResult(BaseModel):
    """
    Shape-only validation. See Segment docstring: all content-level
    checks (segments non-empty, exactly one product, source coverage,
    kind correctness) live in semantic_ai_validation.validate_semantics
    so they can drive repair instead of raising unrecoverably.
    """

    model_config = ConfigDict(extra="forbid")

    segments: list[Segment]
