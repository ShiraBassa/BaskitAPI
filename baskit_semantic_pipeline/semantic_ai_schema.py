from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Role = Literal["product", "brand", "attribute", "unclassified"]


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    role: Role
    kind: str = ""

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("segment text cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_kind(self) -> "Segment":
        if self.role != "attribute":
            if self.kind != "":
                raise ValueError("non-attribute segments must have an empty kind")
            return self

        if not self.kind.strip():
            raise ValueError("attribute kind cannot be empty")

        if self.kind.lower() in {"undefined", "unknown", "null"}:
            raise ValueError("attribute kind cannot be undefined, unknown, or null")

        if any(
            "A" <= char <= "Z" or "a" <= char <= "z"
            for char in self.kind
        ):
            raise ValueError("attribute kind must be Hebrew")

        if not any("\u0590" <= char <= "\u05FF" for char in self.kind):
            raise ValueError("attribute kind must contain Hebrew characters")

        return self


class SemanticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[Segment]

    @field_validator("segments")
    @classmethod
    def segments_must_not_be_empty(cls, value: list[Segment]) -> list[Segment]:
        if not value:
            raise ValueError("segments cannot be empty")
        return value