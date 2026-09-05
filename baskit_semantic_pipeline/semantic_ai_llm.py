from __future__ import annotations

import json
from typing import Any

import requests

from semantic_ai_config import SemanticConfig
from semantic_ai_prompts import SYSTEM_PROMPT, REPAIR_PROMPT
from semantic_ai_schema import SemanticResult


class OllamaSemanticLLM:
    """
    Semantic LLM client using the OpenAI-compatible llama.cpp server.

    Prompt strategy:
        1. SYSTEM_PROMPT is sent in full on every request.
        2. Each product request contains only that product's examples
           followed by the product to parse.
        3. The client never uses /props; prompt caching is handled by llama.cpp.
        4. Prompt caching is enabled so llama.cpp can reuse the shared prompt prefix.
    """


    def __init__(self, config: SemanticConfig):
        self.config = config

        host = config.ollama_host.rstrip("/")

        if host.endswith("/v1"):
            self.base_url = host
        else:
            self.base_url = f"{host}/v1"

        self._session = requests.Session()

        # The full system prompt is sent with every request.
        #
        # IMPORTANT:
        # We do NOT send it through /props.
        # The server currently reports that /props is unsupported.
        self._system_message = {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }

        self._schema_value = {
            "type": "object",
            "properties": {
                "segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "role": {
                                "type": "string",
                                "enum": [
                                    "brand",
                                    "product",
                                    "attribute",
                                    "unclassified",
                                ],
                            },
                            "kind": {"type": "string"},
                        },
                        "required": ["text", "role", "kind"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["segments"],
            "additionalProperties": False,
        }

    @staticmethod
    def _source_order_examples(
        examples: list[dict[str, str]] | None,
    ) -> list[dict[str, str]] | None:
        """
        Return few-shot examples exactly as supplied.

        Example segment order must remain exactly the order represented by
        the source text. No RTL/LTR reversal, reordering, or reconstruction
        is performed here.
        """
        return examples

    @staticmethod
    def _parse_json_content(
        content: str,
    ) -> dict[str, Any]:
        text = content.strip()

        if text.startswith("```"):
            first_newline = text.find("\n")

            if first_newline != -1:
                text = text[first_newline + 1:]

            if text.endswith("```"):
                text = text[:-3].rstrip()

        decoder = json.JSONDecoder()

        start = text.find("{")

        if start == -1:
            raise ValueError(
                f"llama.cpp returned no JSON object: {text!r}"
            )

        payload, _ = decoder.raw_decode(text[start:])

        if not isinstance(payload, dict):
            raise ValueError(
                f"llama.cpp returned non-object JSON: {payload!r}"
            )

        if (
            "segments" not in payload
            and "text" in payload
            and "role" in payload
            and "kind" in payload
        ):
            payload = {
                "segments": [payload],
            }

        return payload

    def _schema(self) -> dict[str, Any]:
        return self._schema_value

    def _chat(
        self,
        messages: list[dict[str, str]],
        *,
        initialize_system: bool = False,
    ) -> str:
        """
        Send a chat request.

        The system prompt is included in full on every request so each
        HTTP request is independently complete. Examples and the current
        product remain request-local.

        Prompt caching is enabled so llama.cpp can reuse the shared prompt prefix.
        No /props request is ever made.
        """

        request_timeout = self.config.request_timeout

        request_messages: list[dict[str, str]] = [self._system_message, *messages]

        request_payload = {
            "model": self.config.model,
            "messages": request_messages,
            "temperature": self.config.temperature,
            "max_tokens": 512,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "semantic_result",
                    "schema": self._schema(),
                },
            },
        }


        response = self._session.post(
            f"{self.base_url}/chat/completions",
            json=request_payload,
            timeout=request_timeout,
        )

        if not response.ok:
            raise requests.HTTPError(
                f"llama.cpp returned HTTP {response.status_code}: "
                f"{response.text}",
                response=response,
            )

        response.raise_for_status()

        result = response.json()
        choices = result.get("choices")

        if not choices:
            raise ValueError(
                f"llama.cpp returned no choices: {result}"
            )

        message = choices[0].get("message", {})
        content = message.get("content")

        if isinstance(content, str):
            content = content.strip()

        if not content:
            reasoning = message.get("reasoning_content")

            if reasoning:
                raise ValueError(
                    "llama.cpp returned reasoning_content but no final "
                    "content. Reasoning was not disabled correctly: "
                    f"{reasoning[:500]}"
                )

            raise ValueError(
                f"llama.cpp returned an empty response: {result}"
            )

        return content

    @staticmethod
    def _normalize_model_output(
        payload: dict[str, Any],
        source_text: str,
    ) -> dict[str, Any]:
        segments = payload.get("segments")

        if not isinstance(segments, list):
            return payload

        normalized_segments = []

        for segment in segments:
            if not isinstance(segment, dict):
                normalized_segments.append(segment)
                continue

            item = dict(segment)

            role = item.get("role")
            kind = item.get("kind")
            attribute_kind = item.get("attribute_kind")

            # Normalize legacy/malformed role fields only.
            #
            # Never infer or relocate semantic segments from their text
            # or punctuation here. Semantic understanding belongs to the model.
            if role not in {
                "brand",
                "product",
                "attribute",
                "unclassified",
            }:
                if kind in {
                    "brand",
                    "product",
                    "attribute",
                    "unclassified",
                }:
                    role = kind
                else:
                    role = "unclassified"

                item["role"] = role

            if role == "attribute":
                item["kind"] = str(
                    kind or attribute_kind or ""
                )
            else:
                item["kind"] = ""

            item.pop("attribute_kind", None)

            normalized_segments.append(item)

        # Deliberately do not reorder, reconstruct, insert, or synthesize
        # source text here.
        #
        # Source preservation is a validation responsibility.
        # The model must produce the correct segmentation itself.
        return {
            **payload,
            "segments": normalized_segments,
        }

    def parse(
        self,
        product_name: str,
        examples: list[dict[str, str]] | None = None,
    ) -> SemanticResult:
        """
        Parse one product.

        Every request contains:
            SYSTEM_PROMPT + examples + product

        The system prompt is sent in full on every request so llama.cpp can cache and reuse the shared prefix.
        Examples are supplied specifically for the product being parsed
        rather than being permanently accumulated into the conversation.
        """

        examples = self._source_order_examples(examples)

        messages: list[dict[str, str]] = []

        if examples:
            messages.extend(examples)

        messages.append(
            {
                "role": "user",
                "content": (
                    "Parse this supermarket product name.\n\n"
                    f"Product name: {product_name}"
                ),
            }
        )

        content = self._chat(messages)

        payload = self._normalize_model_output(
            self._parse_json_content(content),
            product_name,
        )

        return SemanticResult.model_validate(payload)

    def parse_many(
        self,
        product_names: list[str],
        examples_list: list[list[dict[str, str]]] | None = None,
    ) -> list[SemanticResult]:
        """
        Parse products one request at a time.

        Each product gets its own examples.

        The system prompt is initialized only once, on the first product.
        """

        if not product_names:
            return []

        results: list[SemanticResult] = []

        for idx, name in enumerate(product_names):
            examples = (
                examples_list[idx]
                if examples_list and idx < len(examples_list)
                else None
            )

            results.append(
                self.parse(
                    name,
                    examples=examples,
                )
            )

        return results

    def repair(
        self,
        product_name: str,
        previous: SemanticResult,
        issues: list[str],
    ) -> SemanticResult:
        """
        Repair one previous result.

        The repair request includes the full system prompt, the product,
        the previous output, and the validation errors.
        """

        messages = [
            {
                "role": "user",
                "content": (
                    f"Product name: {product_name}\n\n"
                    "Previous output:\n"
                    f"{previous.model_dump_json(ensure_ascii=False)}\n\n"
                    "Validation errors:\n"
                    + "\n".join(
                        f"- {issue}"
                        for issue in issues
                    )
                    + "\n\n"
                    + REPAIR_PROMPT
                ),
            },
        ]

        content = self._chat(messages)

        payload = self._normalize_model_output(
            self._parse_json_content(content),
            product_name,
        )

        return SemanticResult.model_validate(payload)

