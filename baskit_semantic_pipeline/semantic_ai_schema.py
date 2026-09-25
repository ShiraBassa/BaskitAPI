from typing import Literal

from pydantic import BaseModel, ConfigDict


Role = Literal["product", "brand", "attribute", "unclassified"]


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    role: Role
    kind: str = ""


class SemanticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    segments: list[Segment]
