"""Shared response parsing helpers for Baskit's local AI clients."""

from __future__ import annotations

import json

from typing import Any


def decode_json_response(text: Any) -> Any:
    """Decode a JSON object/array from an AI response string."""
    if not isinstance(text, str):
        return None

    text = text.strip()
    if not text:
        return None

    # Handle fenced JSON responses while preserving all Unicode characters.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # First try the complete response.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Then locate a complete JSON object embedded in surrounding text.
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    quoted = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue

        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:index + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    return None

    return None


def items_from_response(parsed: Any) -> list[Any]:
    if (
        isinstance(parsed, dict)
        and isinstance(parsed.get("items"), list)
    ):
        return parsed["items"]
    return []


def text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def valid_hebrew(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False

    if not any("\u0590" <= char <= "\u05FF" for char in value):
        return False

    return not any(
        "a" <= char.lower() <= "z"
        for char in value
    )
