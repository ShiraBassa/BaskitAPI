from __future__ import annotations
import unicodedata

import json
import re
from typing import Any

import requests

from semantic_ai_config import SemanticConfig
from semantic_ai_prompts import (
    SYSTEM_PROMPT,
    BOUNDARY_JUDGE_SYSTEM_PROMPT,
    PARSE_INSTRUCTION,
    REPAIR_PROMPT,
    VERIFY_PROMPT,
    IDENTITY_CONTRACT,
)
from semantic_ai_schema import SemanticResult


def fix_unescaped_hebrew_quotes(raw_text: str) -> str:
    """Escapes unescaped double quotes between Hebrew characters (e.g., ק"ג -> ק\"ג)."""
    return re.sub(r'(?<=[א-ת])"(?=[א-ת])', r'\"', raw_text)


class OllamaSemanticLLM:
    """
    Semantic LLM client using the OpenAI-compatible llama.cpp server.

    Prompt strategy:
        1. SYSTEM_PROMPT is sent in full on every request.
        2. No few-shot or training examples are sent to the model.
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

        self._system_message = {
            "role": "system",
            "content": SYSTEM_PROMPT,
        }

        self._schema_value = {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
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
            "required": ["text", "segments"],
            "additionalProperties": False,
        }

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

        target_text = fix_unescaped_hebrew_quotes(text[start:])

        try:
            payload, _ = decoder.raw_decode(target_text)
        except json.JSONDecodeError as exc:
            print("INVALID MODEL CONTENT:")
            print(repr(text))
            print("JSON ERROR:", exc)
            raise

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

    @staticmethod
    def _extract_product_name_for_json_validation(
        messages: list[dict[str, str]],
    ) -> str:
        for message in reversed(messages):
            content = message.get("content", "")
            marker = "Product name:"
            if marker in content:
                return content.rsplit(marker, 1)[1].split("\n\n", 1)[0].strip()
        return ""

    def _schema(self) -> dict[str, Any]:
        return self._schema_value

    def _chat(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        request_timeout = self.config.request_timeout

        system_message = self._system_message
        if system_prompt is not None:
            system_message = {"role": "system", "content": system_prompt}

        request_messages: list[dict[str, str]] = [system_message, *messages]

        request_payload = {
            "model": self.config.model,
            "messages": request_messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "stream": False,
            "cache_prompt": True,
            "chat_template_kwargs": {
                "enable_thinking": False,
            },
            "response_format": (
                {"type": "json_schema", "json_schema": response_schema}
                if response_schema is not None
                else {"type": "json_object"}
            ),
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

        try:
            result = response.json()
        except ValueError:
            print("RAW LLAMA RESPONSE:")
            print(response.text)
            print("CONTENT-TYPE:", response.headers.get("Content-Type"))
            raise

        choices = result.get("choices")

        if not choices:
            raise ValueError(
                f"llama.cpp returned no choices: {result}"
            )

        message = choices[0].get("message", {})
        content = message.get("content")

        if isinstance(content, str):
            content = content.strip()
        if isinstance(content, str):
            if content.startswith("```"):
                first_newline = content.find("\n")
                if first_newline != -1:
                    content = content[first_newline + 1:]
                if content.endswith("```"):
                    content = content[:-3].rstrip()

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

        return {
            "text": str(payload.get("text", source_text)),
            "segments": normalized_segments,
        }

    def _chat_json(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        previous_content: str | None = None

        for attempt in range(self.config.json_retry_attempts + 1):
            request_messages = list(messages)

            if attempt:
                retry_content = (
                    "The previous response was not valid JSON. Re-emit the same "
                    "semantic answer as exactly one valid JSON object. Do not "
                    "change the semantic segmentation unless required to make "
                    "the JSON valid. Escape every embedded double quote inside "
                    'JSON string values as \\". Do not use markdown fences. Return JSON only.\n'
                )
                if previous_content:
                    retry_content += (
                        "\nPrevious invalid response (repair its JSON syntax):\n"
                        + previous_content
                    )
                request_messages.append({"role": "user", "content": retry_content})

            try:
                content = self._chat(
                    request_messages,
                    system_prompt=system_prompt,
                    response_schema=response_schema,
                )
                previous_content = content
                payload = self._parse_json_content(content)
                return self._normalize_model_output(
                    payload,
                    self._extract_product_name_for_json_validation(messages),
                )
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc

        assert last_error is not None
        raise last_error

    def identify_brand(
        self,
        product_name: str,
    ) -> str:
        """Identify an explicit commercial brand independently of product semantics."""
        schema = {
            "name": "brand_identification",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "brand": {"type": "string"},
                },
                "required": ["text", "brand"],
                "additionalProperties": False,
            },
        }
        # Derive only a structural candidate from the current source. This is
        # not a brand dictionary or a semantic rule: it merely exposes the text
        # on the leading side of a standalone separator to the brand judge.
        # The model still decides whether that candidate is actually commercial
        # identity.
        brand_candidate = ""
        for separator in (" - ", " – ", " — ", ": "):
            if separator in product_name:
                left = product_name.split(separator, 1)[0].strip()
                if left:
                    brand_candidate = left
                    break

        messages = [{
            "role": "user",
            "content": (
                "Identify only the explicit commercial brand in this supermarket title. "
                "This decision is independent of PRODUCT vs ATTRIBUTE. "
                "Do not identify the product and do not classify attributes. "
                "The brand must be an exact contiguous substring of the source, or empty if no explicit brand is present. "
                "If a structural separator divides a leading commercial-name candidate from the product title, "
                "evaluate that candidate specifically as possible commercial identity. "
                "Do not assume that every leading span is a brand; decide from the meaning of the current title. "
                "Do not reject an explicit brand because it can also be read as an ordinary word. "
                "Return only the brand decision.\n\n"
                f"Current title: {product_name}\n"
                f"Leading commercial-identity candidate (if structurally present): {brand_candidate or '[none]'}"
            ),
        }]
        system = (
            "You are Baskit's brand-identification stage. Identify only an explicit commercial brand/manufacturer/retail brand. "
            "Do not decide PRODUCT vs ATTRIBUTE. Return exact source text only. "
            "If the title contains an explicit commercial name separated from the product by punctuation, treat that commercial name as BRAND. "
            "The brand value must be copied character-for-character from the source. Never autocorrect, transliterate, replace, or invent a character. "
            "Do not return a visually similar spelling. Return ONLY JSON."
        )
        payload = self._chat_json(
            messages,
            system_prompt=system,
            response_schema=schema,
        )
        brand = payload.get("brand", "")
        if not isinstance(brand, str):
            brand = ""

        # A brand is a semantic span, not its surrounding separator/punctuation.
        # Normalize only structural punctuation at the edges; never alter the
        # characters inside the brand itself. This is generic and source-grounded.
        import re
        brand = re.sub(r"^[\W_]+|[\W_]+$", "", brand, flags=re.UNICODE).strip()

        # Source-integrity repair only: the semantic stage has already decided
        # that this is a brand. If its spelling is not an exact source span,
        # prefer the exact structural candidate from the current title.
        if brand and brand not in product_name and brand_candidate:
            brand = brand_candidate

        # Source-grounding guard: a brand decision is usable only if it is an
        # exact source substring. If the model accidentally changes a character,
        # ask it once more to copy the source span exactly. No vocabulary list
        # or brand-specific correction is used.
        if brand and brand not in product_name and brand_candidate:
            # The semantic stage has already decided that an explicit brand
            # exists. The structural candidate is the exact source span, so
            # source integrity takes precedence over a misspelled model copy.
            brand = brand_candidate

        if brand and brand not in product_name:
            retry_messages = [
                {
                    "role": "user",
                    "content": (
                        "The previous brand value was not an exact substring of the source. "
                        "Re-read the source and copy the brand character-for-character. "
                        "Do not infer spelling from memory and do not change any source character. "
                        "Return an empty brand only if there is genuinely no explicit commercial brand.\n\n"
                        f"Source title: {product_name}\n"
                        f"Previous brand: {brand}"
                    ),
                }
            ]
            retry_payload = self._chat_json(
                retry_messages,
                system_prompt=system,
                response_schema=schema,
            )
            retry_brand = retry_payload.get("brand", "")
            if isinstance(retry_brand, str):
                retry_brand = re.sub(r"^[\W_]+|[\W_]+$", "", retry_brand, flags=re.UNICODE).strip()
            if isinstance(retry_brand, str) and retry_brand in product_name:
                brand = retry_brand
            else:
                brand = ""

        # If the first independent brand pass returns no brand, give the
        # commercial-identity decision one fresh, isolated adjudication pass.
        # This is semantic and source-grounded; it does not use a vocabulary
        # list or any product/brand-specific exception.
        if not brand:
            retry_messages = [
                {
                    "role": "user",
                    "content": (
                        "Re-evaluate ONLY commercial identity for this current supermarket title. "
                        "Do not solve PRODUCT vs ATTRIBUTE. "
                        "A leading span before a standalone structural separator is provided as a candidate; "
                        "decide semantically whether it is an explicit commercial/manufacturer/retail brand. "
                        "Do not assume the candidate is a brand merely because of its position. "
                        "If it is commercial identity, return that exact source substring as `brand`. "
                        "If it is not commercial identity, return an empty string. "
                        "Do not use memory, prior requests, or product semantics.\n\n"
                        f"Source title: {product_name}\n"
                        f"Leading candidate: {brand_candidate or '[none]'}"
                    ),
                }
            ]
            retry_payload = self._chat_json(
                retry_messages,
                system_prompt=system,
                response_schema=schema,
            )
            retry_brand = retry_payload.get("brand", "")
            if not isinstance(retry_brand, str):
                retry_brand = ""
            retry_brand = re.sub(
                r"^[\W_]+|[\W_]+$",
                "",
                retry_brand,
                flags=re.UNICODE,
            ).strip()
            if retry_brand and retry_brand in product_name:
                brand = retry_brand

        return brand


    def _identify_core_product_raw(self, product_name: str, known_brand: str = "") -> str:
        """Identify the minimum sufficient semantic PRODUCT identity.

        Every possible source-contiguous boundary is evaluated independently
        using the same semantic question:
        does this candidate already identify WHAT product is being bought, or
        is the following text required to identify the product itself?

        The earliest boundary that independently satisfies that test is the
        core. This deliberately separates product identity from version,
        variety, form, target, application, condition, and other attributes.
        """
        source = product_name.strip()
        if not source:
            return ""

        body = source
        if known_brand and known_brand.strip() and body.startswith(known_brand.strip()):
            body = body[len(known_brand.strip()):].lstrip()
            for sep in ("-", "–", "—", ":"):
                if body.startswith(sep):
                    body = body[len(sep):].lstrip()
                    break

        tokens = body.split()
        lexical = []
        for tok in tokens:
            if re.search(r"\d", tok):
                break
            lexical.append(tok)
        if not lexical:
            lexical = tokens[:1]
        if len(lexical) == 1:
            return lexical[0]

        schema = {
            "name": "pairwise_product_identity_boundary",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "classification": {
                        "type": "string",
                        "enum": ["complete_product", "incomplete_family"]
                    }
                },
                "required": ["classification"],
                "additionalProperties": False
            }
        }

        system = IDENTITY_CONTRACT + """You are Baskit's semantic PRODUCT identity judge for Hebrew
supermarket shopping-list titles.

Do not assume that the shortest noun is the product. The task is to find the
minimum SUFFICIENT product identity, not the minimum possible phrase.

You are given ONE candidate PRODUCT prefix and the words that follow it.

Your ONLY question is:

"Does the candidate by itself already tell a shopper WHAT concrete ordinary
supermarket product they are buying, or is some of the following text needed
to know WHAT product it is?"

Return:
- complete_product = the candidate alone gives the shopper a sufficiently informative
  shopping referent. The remaining text can then specify WHICH version, variety,
  form, formulation, processing state, preparation, flavor, color, size, target,
  application, condition, audience, or other property.
- incomplete_family = the candidate alone is too broad or under-informative for the
  shopping request, so the listener would naturally need another word to know WHICH
  product/kind is intended.

CRITICAL:
- Do NOT use "more specific" as the test.
- Do NOT use catalog wording, commercial distinctiveness, searchability,
  grammatical naturalness, or whether the candidate can appear on a list.
- A product can have many varieties and still be a complete product.
- A candidate is NOT incomplete merely because it has varieties. An ordinary
  product category can have many flavors, sizes, forms, or varieties while
  still clearly identifying WHAT product it is.
- Conversely, a candidate can be a real shopping-list word and still be too
  broad to identify the requested product. If it is an umbrella containing
  materially different product categories, and the next word selects which
  category is intended, that next word belongs to PRODUCT.
- Ask whether the shopper who says only the candidate has given enough information
  for a normal shopping request, or whether the listener would naturally ask
  “which product?” / “which kind?” before knowing what to put in the basket.
- A noun can name a real supermarket family and still fail this test.
  “Can this word be bought by itself?” is not the question; “would the shopper
  reasonably need to clarify what kind/product they mean?” is the question.
- Do NOT equate "can be purchased by itself" with "complete product identity".
- Do NOT equate "has varieties" with "incomplete family".
- Decide semantic REFERENT IDENTITY, not word class.

RELATIONAL / APPLICATION RULE:
If the candidate already identifies the concrete product, a following phrase
such as an intended-use, application-area, target, condition, or recipient
description is an ATTRIBUTE. Do not absorb it into PRODUCT merely because the
full phrase sounds like a retail title.

FORM / VERSION / SUBTYPE RULE:
Do not assume that every following form, subtype, variety, color, taste, or
state is automatically an ATTRIBUTE.

First apply the SAME-PRODUCT substitution test:
"If I remove or replace this modifier with another ordinary value, is the shopper
still asking for the same core product, only a different version/property?"
- If YES, the modifier is an ATTRIBUTE.
- If NO, the modifier is required to identify WHAT KIND of product is being
  requested, so it belongs in PRODUCT.

A broad family word can therefore be incomplete even when it is itself a
purchasable supermarket term. Conversely, a clear product can remain complete
when followed by a modifier that only selects a replaceable version/property.

Do this boundary decision BEFORE assigning the modifier's attribute kind.
Never classify something as color/taste/type first and then use that label to
justify making it an ATTRIBUTE.

COUNTERFACTUAL:
Imagine the shopper says ONLY the candidate.

1. Identify the concept the candidate denotes.
2. Ask whether that concept itself is one ordinary supermarket product
   category, or merely an umbrella containing materially different product
   categories.
3. If it is the product category, classify complete_product even when it has
   many flavors, varieties, sizes, or formulations.
4. If it is only an umbrella and the next word selects a distinct product
   category within that umbrella, classify incomplete_family.

The correct boundary is the minimum SUFFICIENT PRODUCT IDENTITY, not the
shortest noun phrase.

A product can have many varieties and still be a complete product.
A word being purchasable by itself does not automatically make it complete.
A word having varieties does not automatically make it incomplete.

The test is SUFFICIENT SHOPPING REFERENT, not “is this technically a product
category?” and not “how specific is the phrase?”.
Never use a product/brand dictionary or a phrase-specific exception.
"""
        results=[]
        # Evaluate each boundary separately. Two independent framings must agree.
        for boundary in range(1,len(lexical)+1):
            candidate=" ".join(lexical[:boundary])
            remainder=" ".join(lexical[boundary:]) or "(none)"
            prompt=(
                f"FULL TITLE: {body}\n"
                f"CANDIDATE PRODUCT: {candidate}\n"
                f"REMAINING WORDS: {remainder}\n\n"
                "Classify the candidate by PRODUCT IDENTITY, using only the "
                "WHAT-vs-WHICH test."
            )
            votes=[]
            for framing in (
                "",
                "\nRe-check only the counterfactual: if the shopper said the "
                "candidate alone, would you know WHAT product to buy?"
            ):
                try:
                    r=self._chat_json(
                        [{"role":"user","content":prompt+framing}],
                        system_prompt=system,
                        response_schema=schema,
                    )
                    c=r.get("classification")
                    if c in {"complete_product","incomplete_family"}:
                        votes.append(c)
                except Exception:
                    pass
            if len(votes)==2 and votes[0]==votes[1]:
                results.append((boundary,votes[0]))

        # TRUE ISOLATED BOUNDARY LOCK.  The left-side judge receives ONLY the
        # candidate prefix; it must not see the full title or suffix.  The
        # suffix judge receives the candidate + suffix relationship and decides
        # only whether the suffix is a specification of that candidate.
        # This prevents familiarity with the full retail phrase from leaking
        # into the product-identity decision.
        if len(lexical) > 1:
            left_schema = {
                "name": "isolated_left_product_identity",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "classification": {"type": "string", "enum": ["complete_product", "incomplete_family"]}
                    },
                    "required": ["classification"],
                    "additionalProperties": False,
                },
            }
            suffix_schema = {
                "name": "isolated_suffix_specification",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "classification": {"type": "string", "enum": ["specification", "identity_completion"]}
                    },
                    "required": ["classification"],
                    "additionalProperties": False,
                },
            }
            left_system = IDENTITY_CONTRACT + """You are an isolated PRODUCT identity judge.
You receive ONLY the candidate text. You do not know the original title, any
following words, brand, or retail phrase. Decide whether this candidate alone
identifies one ordinary concrete supermarket product category.
Return complete_product if yes. Return incomplete_family only if the candidate
is itself an umbrella containing materially different product categories.
Do not use lexical familiarity or imagine missing words.
"""
            suffix_system = IDENTITY_CONTRACT + """You are an isolated PRODUCT-SPECIFICATION judge.
You receive a candidate product and a following span. Decide only whether the
following span specifies WHICH version/property/member/state/formulation/use
condition/processing/flavor/variety/etc. of that candidate is wanted, while
leaving the underlying product category unchanged.
Return specification when it is a property/version of the candidate. Return
identity_completion only when the following span is needed to identify WHAT
product category is being requested. Do not decide based on retail phrase
familiarity or on whether the complete phrase is commercially named.
"""
            isolated_boundaries = []
            for boundary in range(1, len(lexical)):
                candidate = " ".join(lexical[:boundary])
                following = " ".join(lexical[boundary:])
                left_votes = []
                right_votes = []
                for framing in (
                    "",
                    "\nRe-check the candidate in isolation. Do not infer anything from a suffix you cannot see.",
                ):
                    try:
                        lr = self._chat_json(
                            [{"role": "user", "content": f"CANDIDATE ONLY:\n{candidate}" + framing}],
                            system_prompt=left_system,
                            response_schema=left_schema,
                        )
                        if lr.get("classification") in ("complete_product", "incomplete_family"):
                            left_votes.append(lr["classification"])
                    except Exception:
                        pass
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": f"CANDIDATE PRODUCT:\n{candidate}\n\nFOLLOWING SPAN:\n{following}" + framing}],
                            system_prompt=suffix_system,
                            response_schema=suffix_schema,
                        )
                        if rr.get("classification") in ("specification", "identity_completion"):
                            right_votes.append(rr["classification"])
                    except Exception:
                        pass
                if (len(left_votes) == 2 and left_votes[0] == left_votes[1] == "complete_product"
                        and len(right_votes) == 2 and right_votes[0] == right_votes[1] == "specification"):
                    isolated_boundaries.append(boundary)
            # Isolated evidence is deliberately non-authoritative. A candidate
            # can look complete when seen alone even though the following word
            # is required to resolve which product category is intended.
            isolated_boundary_candidates = isolated_boundaries

        # PRIORITY REFERENT-RESOLUTION AUDIT.
        #
        # This comparison must happen before any "attribute" boundary is
        # accepted. The key question is not whether PREFIX can exist alone,
        # but whether PREFIX already denotes the same product category after
        # the next word is added.
        #
        # This is the semantic distinction between cases such as:
        #   סוכר + לבן      -> same product category, attribute
        #   גבינה + לבנה    -> added word resolves the product category
        #
        # No lexical list or product-specific exception is used.
        if len(lexical) > 1:
            referent_schema = {
                "name": "priority_product_referent_resolution",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": [
                                "same_product_category",
                                "category_resolution_required",
                            ],
                        }
                    },
                    "required": ["decision"],
                    "additionalProperties": False,
                },
            }
            referent_system = IDENTITY_CONTRACT + """You are the PRIMARY
semantic product-category boundary judge.

Compare PREFIX with PREFIX + NEXT_WORD.

The question is NOT whether PREFIX can appear on a shopping list.
The question is whether PREFIX already identifies the product category the
shopper is asking for.

Return SAME_PRODUCT_CATEGORY only when PREFIX already identifies a sufficiently
clear product category and NEXT_WORD merely chooses a member, version, property,
form, variety, flavor, color, formulation, preparation, processing state,
preservation state, size, audience, application, or other attribute of that
same category.

Return CATEGORY_RESOLUTION_REQUIRED when NEXT_WORD is needed to answer WHAT
PRODUCT CATEGORY is being requested because PREFIX by itself is an umbrella,
family, or otherwise under-specified shopping referent.

IMPORTANT:
- Do not confuse a product category with an umbrella family.
- Do not confuse "has many varieties" with "is an umbrella".
- Variants of the same category remain attributes.
- If different plausible values of NEXT_WORD would correspond to materially
  different product categories rather than members/properties of one category,
  NEXT_WORD is product identity.
- Ask: "If the shopper stopped after PREFIX, would I know which product
  category to select, or would I still need to know what kind of product?"
- Decide the product-category boundary BEFORE deciding whether NEXT_WORD is
  color, taste, type, etc.
- Ignore retail phrase familiarity and grammatical naturalness.
- Never use dictionaries, phrase lists, regexes, or benchmark-specific
  exceptions.
"""
            referent_decisions = []
            for boundary in range(1, len(lexical)):
                prefix = " ".join(lexical[:boundary])
                next_word = lexical[boundary]
                expanded = " ".join(lexical[:boundary + 1])
                prompt = (
                    f"FULL TITLE: {body}\n"
                    f"PREFIX: {prefix}\n"
                    f"NEXT WORD: {next_word}\n"
                    f"EXPANDED: {expanded}\n\n"
                    "Compare PREFIX with EXPANDED and decide whether the next "
                    "word changes/resolves the product category."
                )
                votes = []
                for framing in (
                    "",
                    "\nIndependent check: answer only the product-category "
                    "question; do not classify the next word as an attribute "
                    "until after deciding the boundary."
                ):
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": prompt + framing}],
                            system_prompt=referent_system,
                            response_schema=referent_schema,
                        )
                        d = rr.get("decision")
                        if d in (
                            "same_product_category",
                            "category_resolution_required",
                        ):
                            votes.append(d)
                    except Exception:
                        pass
                if len(votes) == 2 and votes[0] == votes[1]:
                    referent_decisions.append((boundary, votes[0]))

            # The first boundary whose next word does NOT change product
            # category is the minimum sufficient PRODUCT identity. If the next
            # word resolves the category, continue to the next boundary.
            for boundary, decision in referent_decisions:
                if decision == "same_product_category":
                    return " ".join(lexical[:boundary])

        # Final boundary adjudication. Evaluate every internal boundary
        # directly instead of allowing the shortest-prefix result to decide.
        if len(lexical) > 1:
            boundary_schema = {
                "name": "minimum_sufficient_product_boundary",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": ["boundary_here", "need_more_product"]
                        }
                    },
                    "required": ["decision"],
                    "additionalProperties": False
                }
            }
            boundary_system = IDENTITY_CONTRACT + """You are the final semantic PRODUCT-boundary adjudicator.

CANDIDATE is the text before the proposed boundary.
FOLLOWING is the text after it.

Return boundary_here when CANDIDATE alone identifies WHAT PRODUCT CATEGORY
the shopper is requesting and FOLLOWING only describes WHICH property/version.

Return need_more_product when FOLLOWING is still necessary to identify WHAT
PRODUCT CATEGORY is being requested.

If CANDIDATE is an umbrella containing materially different product categories
and FOLLOWING selects which category, return need_more_product.

If CANDIDATE is already one product category, then flavor, variety, color,
size, formulation, preparation, processing, target, application, condition,
audience, or presentation in FOLLOWING is an attribute.

Do not infer PRODUCT from a modifier merely because the complete phrase is a
familiar retail/catalog expression. A familiar phrase can still be PRODUCT +
ATTRIBUTE. First determine whether FOLLOWING denotes a property of CANDIDATE by
asking what changes if FOLLOWING is replaced by another value. If only that
property changes while the underlying product category remains, the boundary
belongs before FOLLOWING.

Do not choose the shortest noun phrase automatically.
Do not choose the longest retail phrase automatically.
"More specific" is not the test.
A product category may have many varieties and remain one product category.

Decide what changes in the answer to: WHAT PRODUCT CATEGORY is this?
Ignore grammar, catalog style, searchability, and phrase familiarity.
Before deciding, use the contrastive calibration in the shared contract as a semantic reference. Do not match words; compare the underlying product referent and distinguish category identity from member/version/property.
"""
            decisions = []
            for boundary in range(1, len(lexical)):
                candidate = " ".join(lexical[:boundary])
                following = " ".join(lexical[boundary:])
                prompt = (
                    f"FULL TITLE: {body}\n"
                    f"CANDIDATE: {candidate}\n"
                    f"FOLLOWING: {following}\n\n"
                    "Judge this boundary using product identity only."
                )
                votes = []
                for extra in (
                    "",
                    "\nIndependently re-check: would the shopper know WHAT PRODUCT "
                    "CATEGORY to buy from CANDIDATE alone?"
                ):
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": prompt + extra}],
                            system_prompt=boundary_system,
                            response_schema=boundary_schema,
                        )
                        if rr.get("decision") in ("boundary_here", "need_more_product"):
                            votes.append(rr["decision"])
                    except Exception:
                        pass
                if len(votes) == 2 and votes[0] == votes[1]:
                    decisions.append((boundary, votes[0]))

            # Keep these as evidence only. Do not commit to the earliest
            # boundary yet: a later referent comparison may show that the
            # following word is required to resolve the product category.
            early_boundary_candidates = [
                boundary for boundary, decision in decisions
                if decision == "boundary_here"
            ]

        complete = {b for b, c in results if c == "complete_product"}

        # Final semantic contraction audit. Re-check every shorter prefix as a
        # possible complete product against its exact suffix. This provides a
        # second route to the minimum sufficient identity when an earlier
        # boundary judge is uncertain. The decision is semantic, not lexical.
        if len(lexical) > 1:
            contraction_schema = {
                "name": "product_attribute_contraction_audit",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": ["same_product_attribute", "required_product_identity"]
                        }
                    },
                    "required": ["decision"],
                    "additionalProperties": False,
                },
            }
            contraction_system = IDENTITY_CONTRACT + """You are the final
semantic PRODUCT contraction auditor.

Compare PREFIX with PREFIX + SUFFIX. Return same_product_attribute when PREFIX
already identifies the same concrete ordinary supermarket product referent and
SUFFIX only specifies a property, variety, version, flavor, color, formulation,
processing state, size, target, audience, application, or presentation.
Return required_product_identity when SUFFIX completes or disambiguates the
actual product referent/category, including when PREFIX is an ambiguous
shorthand or umbrella and SUFFIX identifies the substance/species/object that
makes the requested product concrete. Do not treat an informal standalone use
of PREFIX as proof that it is the same referent.

Do not use retail naming conventions, phrase familiarity, or searchability.
A familiar commercial phrase can still contain PRODUCT + ATTRIBUTE.
Use property substitution: if replacing SUFFIX with another value changes only
a property/member/version of the same product category, SUFFIX is an attribute.
"""
            for boundary in range(1, len(lexical)):
                prefix = " ".join(lexical[:boundary])
                suffix = " ".join(lexical[boundary:])
                prompt = (
                    f"FULL TITLE: {body}\n"
                    f"PREFIX PRODUCT CANDIDATE: {prefix}\n"
                    f"SUFFIX: {suffix}\n\n"
                    "Determine whether SUFFIX is a specification of PREFIX or is "
                    "required to identify the product category."
                )
                votes = []
                for extra in (
                    "",
                    "\nRe-check by property substitution: what changes if SUFFIX is replaced?",
                ):
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": prompt + extra}],
                            system_prompt=contraction_system,
                            response_schema=contraction_schema,
                        )
                        if rr.get("decision") in (
                            "same_product_attribute",
                            "required_product_identity",
                        ):
                            votes.append(rr["decision"])
                    except Exception:
                        pass
                if len(votes) == 2 and votes[0] == votes[1] and votes[0] == "same_product_attribute":
                    return prefix

        # Final attribute-aware boundary pass. This is deliberately independent
        # from the earlier product-boundary votes: it evaluates the LEFT side as
        # a product referent and the RIGHT side as a semantic attribute span.
        # This prevents a model from swallowing a clearly attributable suffix
        # merely because the complete phrase sounds like a retail product name.
        if len(lexical) > 1:
            attr_boundary_schema = {
                "name": "attribute_aware_product_boundary",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": [
                                "product_here",
                                "need_more_identity"
                            ]
                        }
                    },
                    "required": ["decision"],
                    "additionalProperties": False,
                },
            }
            attr_boundary_system = IDENTITY_CONTRACT + """You are an
independent final PRODUCT-boundary judge.

CANDIDATE is the proposed product span. SUFFIX is everything immediately after
it in the product body.

First determine whether CANDIDATE alone identifies the ordinary supermarket
product referent being requested.

Then determine what semantic role SUFFIX has if CANDIDATE is treated as the
product. SUFFIX may express taste, smell, color, material, quantity, fat
percentage, size, dimensions, audience, application/condition, formulation,
variety, subtype, preparation, processing, preservation, presentation, or
another specification.

Return product_here when BOTH are true:
1. CANDIDATE already identifies WHAT product is being bought.
2. SUFFIX can naturally be understood as specifying WHICH version/property of
   that product.

Return need_more_identity when CANDIDATE is only an umbrella/broad family,
or when SUFFIX is required to identify WHAT concrete product/referent is meant.

CRITICAL:
- Do not make the product longer merely because SUFFIX is semantically
  important.
- Do not make the product shorter merely because CANDIDATE is a word that can
  occur alone on a shopping list.
- A product can have many varieties and still be complete.
- A modifier can be a noun, adjective, prepositional phrase, or relational
  phrase and still be an attribute.
- Decide the referent of CANDIDATE in ordinary shopping context, not its
  dictionary meaning.
- Evaluate the whole SUFFIX as a possible attribute before deciding that any
  part of it completes product identity.
- If CANDIDATE is already a concrete product and SUFFIX describes flavor,
  processing, formulation, preparation, variety, target/condition, or another
  version/property, return product_here.
- If CANDIDATE is an umbrella and SUFFIX identifies which materially different
  product class is intended, return need_more_identity.

Do not use dictionaries, phrase lists, brand lists, regexes, or
benchmark-specific exceptions. Return only the decision."""
            attr_decisions = []
            for boundary in range(1, len(lexical)):
                candidate = " ".join(lexical[:boundary])
                suffix = " ".join(lexical[boundary:])
                prompt = (
                    f"FULL TITLE: {body}\n"
                    f"CANDIDATE PRODUCT: {candidate}\n"
                    f"SUFFIX: {suffix}\n\n"
                    "Judge whether the boundary belongs before SUFFIX."
                )
                votes = []
                for extra in (
                    "",
                    "\nIndependent check: classify the suffix semantically first, "
                    "then ask whether the candidate alone names the same product referent."
                ):
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": prompt + extra}],
                            system_prompt=attr_boundary_system,
                            response_schema=attr_boundary_schema,
                        )
                        d = rr.get("decision")
                        if d in ("product_here", "need_more_identity"):
                            votes.append(d)
                    except Exception:
                        pass
                if len(votes) == 2 and votes[0] == votes[1]:
                    attr_decisions.append((boundary, votes[0]))

            for boundary, decision in attr_decisions:
                if decision == "product_here":
                    return " ".join(lexical[:boundary])

        if complete:
            earliest = min(complete)

            # Final referent disambiguation for an otherwise ambiguous
            # boundary. Compare the candidate with the candidate plus the next
            # word and determine whether the next word changes the PRODUCT
            # CATEGORY itself. This is deliberately not a lexical rule.
            if earliest < len(lexical):
                candidate = " ".join(lexical[:earliest])
                expanded = " ".join(lexical[:earliest + 1])

                disamb_schema = {
                    "name": "product_referent_disambiguation",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "classification": {
                                "type": "string",
                                "enum": [
                                    "same_product_attribute",
                                    "different_product_identity"
                                ]
                            }
                        },
                        "required": ["classification"],
                        "additionalProperties": False
                    }
                }

                disamb_system = """You are a semantic supermarket PRODUCT
referent judge.

Compare CANDIDATE and EXPANDED.

Return same_product_attribute when EXPANDED still refers to the same concrete
ordinary product referent as CANDIDATE and merely specifies a property/version
such as flavor, color, size, formulation, processing, preparation, target,
application, condition, audience, or variety. If the added word completes the
name/referent of what is being purchased rather than describing that referent,
return different_product_identity.

Return different_product_identity when EXPANDED identifies a different
product category from CANDIDATE, because CANDIDATE is only an umbrella/family
and the added word is necessary to know WHAT PRODUCT is being requested.

Important:
- Do not decide from the adjective/noun's dictionary meaning alone.
- Do not assume food adjectives are colors or flavors without considering the
  product referent.
- Do not assume a longer phrase is a different product merely because it is
  commercially natural.
- The question is whether the shopper's answer to "WHAT PRODUCT CATEGORY?"
  changes.
"""
                prompt = (
                    f"FULL TITLE: {body}\n"
                    f"CANDIDATE: {candidate}\n"
                    f"EXPANDED: {expanded}\n"
                    f"FOLLOWING: {' '.join(lexical[earliest+1:]) or '(none)'}"
                )

                votes = []
                for extra in (
                    "",
                    "\nIndependent check: ignore wording familiarity and compare "
                    "the actual product referents of CANDIDATE and EXPANDED."
                ):
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": prompt + extra}],
                            system_prompt=disamb_system,
                            response_schema=disamb_schema,
                        )
                        value = rr.get("classification")
                        if value in (
                            "same_product_attribute",
                            "different_product_identity"
                        ):
                            votes.append(value)
                    except Exception:
                        pass

                if len(votes) == 2 and votes[0] == votes[1]:
                    if votes[0] == "different_product_identity":
                        # Continue to the next boundary only if it is also
                        # semantically complete according to the existing
                        # boundary adjudication.
                        for boundary, decision in decisions:
                            if (
                                boundary > earliest
                                and decision == "boundary_here"
                            ):
                                return " ".join(lexical[:boundary])
                    else:
                        return candidate

            return " ".join(lexical[:earliest])


        # Conservative fallback: use the existing semantic boundary judge only
        # if the independent pairwise adjudication did not obtain enough
        # agreement. This preserves prior behavior on malformed/model-failure
        # cases without introducing lexical shortcuts.
        fallback_schema = {
            "name":"semantic_core_boundary_fallback",
            "strict":True,
            "schema":{
                "type":"object",
                "properties":{
                    "product":{"type":"string"}
                },
                "required":["product"],
                "additionalProperties":False
            }
        }
        fallback_system = IDENTITY_CONTRACT + """Identify the minimum sufficient core supermarket
product in the supplied title.

Use the same WHAT-vs-WHICH identity test:
if a candidate already tells the shopper WHAT product to buy, later words are
attributes; if the candidate is only a broad family and later words are needed
to identify WHAT product it is, keep those words in PRODUCT.

Relational target/application/condition phrases are attributes once the base
already identifies the product. Form/version/variety words are attributes once
the base already identifies the product. Never choose a longer product merely
because it sounds like a natural catalog phrase.

Return an exact contiguous source span from the title. Do not normalize,
lemmatize, invent, or rewrite text."""
        try:
            r=self._chat_json(
                [{"role":"user","content":f"TITLE: {body}"}],
                system_prompt=fallback_system,
                response_schema=fallback_schema,
            )
            candidate=str(r.get("product") or "").strip()
            if candidate and candidate in body:
                return candidate
        except Exception:
            pass

        return lexical[0]

    def identify_core_product(self, product_name: str, known_brand: str = "") -> str:
        """Identify the core product, then independently audit only its final modifier.

        The audit is deliberately one-step only: it can contract a selected core
        from BASE + FINAL_MODIFIER to BASE, but it never recursively strips words.
        This preserves multi-word category-defining cores such as a concrete
        product family plus its category-defining modifier.
        """
        core = self._identify_core_product_raw(
            product_name,
            known_brand=known_brand,
        ).strip()

        if not core:
            return core

        # Reconstruct the exact product body used by the raw boundary stage.
        # This method owns the later audits, so it must derive `body` locally
        # rather than relying on the local variable from `_identify_core_product_raw`.
        source = product_name.strip()
        body = source
        if known_brand and known_brand.strip() and body.startswith(known_brand.strip()):
            body = body[len(known_brand.strip()):].lstrip()
            for sep in ("-", "–", "—", ":"):
                if body.startswith(sep):
                    body = body[len(sep):].lstrip()
                    break

        # Full-body semantic boundary adjudication. Re-evaluate every prefix of
        # the product body because an earlier stage may already have over-absorbed
        # a flavor, variety, processing state, or application condition.
        body_tokens = body.split()

        # AUTHORITATIVE ATTRIBUTE-FIRST BOUNDARY LOCK.
        # Evaluate each possible boundary independently.  Unlike the earlier
        # multi-candidate judges, each call sees exactly one BASE/ADDITION pair.
        # A boundary is eligible only when independent votes agree that:
        #   (a) BASE already identifies the product referent, and
        #   (b) ADDITION is a specification of that BASE.
        # This keeps semantic attribute evidence from being drowned out by
        # familiarity with the complete retail expression.
        if len(body_tokens) >= 2:
            pair_schema = {
                "name": "single_boundary_semantic_lock",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "base_status": {
                            "type": "string",
                            "enum": ["complete_product", "incomplete_family"],
                        },
                        "addition_status": {
                            "type": "string",
                            "enum": ["attribute", "identity_completion"],
                        },
                    },
                    "required": ["base_status", "addition_status"],
                    "additionalProperties": False,
                },
            }
            pair_system = IDENTITY_CONTRACT + """
You are a semantic boundary judge for a Hebrew supermarket shopping title.

Evaluate ONE boundary only. Do not compare it with other boundaries.

BASE is the text before the boundary. ADDITION is all source text after it
up to the end of the lexical product body.

Answer two independent questions.

QUESTION 1 — BASE:
If a shopper wrote only BASE on an ordinary shopping list, would the listener
know WHAT concrete supermarket product category/referent is being requested?
- complete_product = yes
- incomplete_family = no, because ADDITION is necessary to identify WHAT
  product category is meant.

QUESTION 2 — ADDITION:
Assuming BASE is the product, does ADDITION specify WHICH version/property of
that product, rather than changing WHAT product category it is?
- attribute = it expresses flavor, variety, subtype, formulation, preparation,
  processing, state, presentation, color, material, size, dimension, audience,
  application/condition, or another property of an already identified product.
- identity_completion = it is needed to identify the product category itself.

IMPORTANT:
Do not use retail-name familiarity, catalog wording, searchability, grammar,
or phrase frequency as evidence.
Do not decide from one word in isolation.
Judge the complete BASE and complete ADDITION as semantic referents.

A broad product with ordinary varieties can still be complete. A broad umbrella
that leaves materially different product categories unresolved is incomplete.
A modifier can be an ATTRIBUTE even when the resulting phrase is a common
commercial product name.

For an application/condition phrase after an already identified personal-care
product, treat the target/condition as a specification unless it changes WHAT
the product itself is.
For a food noun after an already identified product, determine whether it
changes the sensory flavor/variety/property of that product or completes a
different product category. Do not infer from the noun alone.

Return only the two classifications.
"""
            accepted_boundaries = []
            # Earliest qualifying boundary is authoritative.
            for boundary in range(1, len(body_tokens)):
                base = " ".join(body_tokens[:boundary])
                addition = " ".join(body_tokens[boundary:])
                prompt = (
                    f"FULL PRODUCT BODY: {body}\n"
                    f"BASE: {base}\n"
                    f"ADDITION: {addition}\n\n"
                    "Evaluate this single boundary."
                )
                votes = []
                for framing in (
                    "",
                    "\nSecond independent evaluation: ignore whether the full "
                    "expression looks like a familiar product name. Recompute "
                    "BASE referent and ADDITION semantic role from scratch.",
                ):
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": prompt + framing}],
                            system_prompt=pair_system,
                            response_schema=pair_schema,
                        )
                        if (
                            rr.get("base_status") == "complete_product"
                            and rr.get("addition_status") == "attribute"
                        ):
                            votes.append(True)
                        else:
                            votes.append(False)
                    except Exception:
                        votes.append(False)
                if votes == [True, True]:
                    accepted_boundaries.append(boundary)
                    break
            if accepted_boundaries:
                core = " ".join(body_tokens[:accepted_boundaries[0]])
        if len(body_tokens) >= 2:
            full_schema = {
                "name": "full_body_product_boundary_adjudication",
                "strict": True,
                "schema": {"type": "object", "properties": {
                    "boundary": {"type": "integer", "minimum": 1, "maximum": len(body_tokens)}
                }, "required": ["boundary"], "additionalProperties": False}
            }
            full_candidates = "\\n".join(
                f"{i}: BASE='{ ' '.join(body_tokens[:i]) }' | ADDITION='{ ' '.join(body_tokens[i:]) }'"
                for i in range(1, len(body_tokens) + 1)
            )
            full_system = IDENTITY_CONTRACT + """You are an independent semantic PRODUCT boundary judge for a supermarket shopping title.

Choose the earliest boundary that identifies the actual product being requested.
Do not choose based on retail phrase familiarity, catalog wording, searchability, or grammar.

For every candidate BASE:
1. Imagine the shopper said only BASE.
2. Determine the concrete product category/referent the listener would understand.
3. Add ADDITION back.
4. Decide whether ADDITION merely specifies a property/version of that same product,
   or is necessary to identify a different concrete product category/referent.

If BASE already identifies the product, flavor, variety, processing/state, formulation,
texture, color, or application/condition wording remains an attribute. If BASE is only a
broad family and the addition is needed to know WHAT concrete product is intended, keep
the necessary addition inside PRODUCT.

A relational/application phrase can be part of PRODUCT only when the completed relation
changes WHAT concrete product category is being requested. A hair/skin/body condition
following an already identified personal-care product is normally a use/version attribute.
Compound nouns that complete the concrete referent must not be shortened merely because
the first noun can appear independently on a shopping list.

Do not use dictionaries, phrase lists, brand lists, regexes, or benchmark-specific rules.
Return only the boundary number."""
            full_prompt = (
                f"FULL TITLE: {product_name}\\nCURRENT CORE FROM EARLIER STAGES: {core}\\n\\n"
                f"ALL PRODUCT-BODY BOUNDARIES:\\n{full_candidates}\\n\\n"
                "Select the minimum SUFFICIENT PRODUCT boundary using the SAME-PRODUCT substitution test, not the shortest boundary."
            )
            full_votes=[]
            for extra in (
                "",
                "\\nIndependently recompute the referent. Do not preserve a longer core merely because the full phrase is a familiar retail expression."
            ):
                try:
                    rr=self._chat_json([{"role":"user","content":full_prompt+extra}], system_prompt=full_system, response_schema=full_schema)
                    b=rr.get("boundary")
                    if isinstance(b,int) and 1 <= b <= len(body_tokens): full_votes.append(b)
                except Exception:
                    pass
            if len(full_votes)==2 and full_votes[0]==full_votes[1]:
                candidate=" ".join(body_tokens[:full_votes[0]])
                if candidate: core=candidate


        # Attribute-aware whole-body adjudication. Unlike the boundary judges
        # above, this stage does not ask which boundary "sounds most complete".
        # It first determines whether the suffix itself is semantically an
        # attribute of the prefix. This gives semantic attribute evidence a
        # direct vote in boundary selection and prevents an attribute-bearing
        # suffix from being swallowed simply because the full phrase is a
        # familiar retail expression.
        if len(body_tokens) >= 2:
            suffix_schema = {
                "name": "suffix_attribute_boundary_adjudication",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "boundary": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": len(body_tokens),
                        },
                        "suffix_role": {
                            "type": "string",
                            "enum": ["attribute", "identity_completion"],
                        },
                    },
                    "required": ["boundary", "suffix_role"],
                    "additionalProperties": False,
                },
            }
            suffix_system = IDENTITY_CONTRACT + """
You are an independent semantic boundary adjudicator.

For every possible split of the product body, evaluate the LEFT side as a
candidate product and the RIGHT side as one semantic unit.

First determine whether the LEFT side already identifies WHAT concrete
supermarket product is being requested.

Then determine whether the RIGHT side describes WHICH version/property of
that product. A RIGHT side is an ATTRIBUTE when it expresses any ordinary
product specification such as:
- flavor or sensory profile
- variety or subtype
- formulation or composition
- texture or consistency
- preparation or processing
- preservation/state
- presentation/form
- color, material, size, dimension
- intended audience
- application/use target or condition
- another property of an already identified product

An RIGHT side is IDENTITY_COMPLETION only when the LEFT side is not yet a
sufficient product referent and the RIGHT side is needed to know WHAT product
category the shopper means.

IMPORTANT:
Do not decide from the fact that the complete phrase is commonly printed as
one retail name. Retail naming is not the semantic boundary.

Do not decide from a single word's dictionary meaning. Evaluate the complete
RIGHT side in relation to the LEFT product.

For relational phrases, evaluate the complete relation as one semantic unit.
A target or condition can be an attribute when it selects a use-specific
version of an already identified product. Do not confuse an application
condition with the identity of the product itself.

For food/product nouns used after a base product, determine whether the
addition changes the product's sensory flavor/variety/composition or instead
completes a materially different product category. The semantic relationship
controls the boundary.

Choose the EARLIEST split for which:
1. LEFT is a complete product referent, and
2. RIGHT is an ATTRIBUTE.

Never rewrite or normalize the source. Do not use dictionaries, phrase lists,
brand lists, regexes, or benchmark-specific exceptions.
"""
            suffix_candidates = "\n".join(
                f"{i}: LEFT='{ ' '.join(body_tokens[:i]) }' | RIGHT='{ ' '.join(body_tokens[i:]) }'"
                for i in range(1, len(body_tokens))
            )
            suffix_prompt = (
                f"FULL TITLE: {product_name}\n"
                f"CURRENT CORE: {core}\n\n"
                f"ALL POSSIBLE PRODUCT-BODY SPLITS:\n{suffix_candidates}\n\n"
                "Return the earliest split where LEFT is already the product "
                "and RIGHT is an attribute."
            )
            suffix_votes = []
            for framing in (
                "",
                "\nRe-evaluate each split from the semantic role of the complete "
                "RIGHT side. Do not preserve a longer product merely because "
                "the complete expression is a familiar product label.",
            ):
                try:
                    rr = self._chat_json(
                        [{"role": "user", "content": suffix_prompt + framing}],
                        system_prompt=suffix_system,
                        response_schema=suffix_schema,
                    )
                    b = rr.get("boundary")
                    role = rr.get("suffix_role")
                    if (
                        isinstance(b, int)
                        and 1 <= b < len(body_tokens)
                        and role == "attribute"
                    ):
                        suffix_votes.append(b)
                except Exception:
                    pass
            if len(suffix_votes) == 2 and suffix_votes[0] == suffix_votes[1]:
                candidate = " ".join(body_tokens[:suffix_votes[0]])
                if candidate:
                    core = candidate

        # Conservative whole-core prefix audit. This is intentionally separate
        # from the final-token audit below because a relational/application
        # construction or a categorical modifier can occur more than one token
        # inside a model-selected core.
        body = product_name.strip()
        if known_brand and known_brand.strip() and body.startswith(known_brand.strip()):
            body = body[len(known_brand.strip()):].lstrip()
            for sep in ("-", "–", "—", ":"):
                if body.startswith(sep):
                    body = body[len(sep):].lstrip()
                    break

        core_tokens = core.split()
        if len(core_tokens) >= 2:
            prefix_schema = {
                "name": "whole_core_prefix_audit",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "boundary": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": len(core_tokens)
                        }
                    },
                    "required": ["boundary"],
                    "additionalProperties": False
                }
            }

            candidates = "\n".join(
                f"{i}: '{' '.join(core_tokens[:i])}' | remainder: '{' '.join(core_tokens[i:])}'"
                for i in range(1, len(core_tokens) + 1)
            )

            prefix_system = IDENTITY_CONTRACT + """You are the final independent semantic PRODUCT-boundary auditor.

A previous stage selected this PRODUCT core, but it may be too long.
Evaluate every internal prefix of that selected core.

Choose the EARLIEST prefix that already identifies the concrete ordinary
supermarket product being requested.

Use this exact distinction:
- If the prefix alone identifies WHAT product is being bought, later words
  are attributes describing WHICH version, formulation, processing state,
  variety, target, application, condition, form, or other specification.
- If the prefix is only a broad family and the next word is needed to know
  WHAT product category is intended, the prefix is incomplete and the boundary
  must remain later.

Do not use phrase familiarity, catalog wording, searchability, or grammatical
completeness as evidence.

For relational/prepositional constructions, do not automatically absorb the
whole relation into PRODUCT. Test the base before the relation. If the base
already identifies the product, the relation is an attribute. If a part of the
relation is genuinely necessary for product identity, the boundary may extend
into that relation, but later target/condition/variety wording remains an
attribute.

For ordinary categorical modifiers such as preparation, form, subtype,
processing, or variety, apply the same WHAT-vs-WHICH test.

COMPOUND-IDENTITY CHECK:
Before shortening a selected multi-word PRODUCT, determine whether the removed
word is merely a property of the remaining product or whether it completes the
identity of the thing being purchased. If it completes the referent/category,
it must remain in PRODUCT. Do not shorten a compound product name to an
ambiguous shorthand noun merely because that noun can appear independently on
a shopping list.

Important:
- Return a boundary into the SELECTED CORE only.
- The returned product must be an exact contiguous source span.
- Do not invent, normalize, reorder, or rewrite text.
- Do not use product names, dictionaries, phrase lists, or benchmark-specific
  exceptions.
"""
            prefix_prompt=(
                f"FULL TITLE: {product_name}\n"
                f"SELECTED CORE: {core}\n\n"
                f"INTERNAL CANDIDATES:\n{candidates}\n\n"
                "Return the earliest semantically complete product boundary."
            )

            audited=[]
            for extra in (
                "",
                "\nRe-check the earliest candidate specifically. Do not let a natural "
                "multi-word retail phrase override the WHAT-vs-WHICH test."
            ):
                try:
                    result=self._chat_json(
                        [{"role":"user","content":prefix_prompt+extra}],
                        system_prompt=prefix_system,
                        response_schema=prefix_schema,
                    )
                    b=result.get("boundary")
                    if isinstance(b,int) and 1 <= b <= len(core_tokens):
                        audited.append(b)
                except Exception:
                    pass

            if len(audited) == 2 and audited[0] == audited[1]:
                candidate=" ".join(core_tokens[:audited[0]])
                if candidate and candidate != core:
                    core=candidate

        if known_brand and known_brand.strip() and body.startswith(known_brand.strip()):
            body = body[len(known_brand.strip()):].lstrip()
            for sep in ("-", "–", "—", ":"):
                if body.startswith(sep):
                    body = body[len(sep):].lstrip()
                    break

        core_tokens = core.split()
        if len(core_tokens) < 2:
            return core

        base = " ".join(core_tokens[:-1])
        modifier = core_tokens[-1]

        # Only audit a final modifier that is actually part of the selected core.
        # Never use a lexical dictionary or a product-specific exception.
        schema = {
            "name": "final_modifier_core_identity_audit",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "modifier_role": {
                        "type": "string",
                        "enum": ["attribute", "core_defining"]
                    },
                    "base_identity": {
                        "type": "string",
                        "enum": ["complete_product", "incomplete_family"]
                    }
                },
                "required": ["modifier_role", "base_identity"],
                "additionalProperties": False
            }
        }

        system = IDENTITY_CONTRACT + """You are an independent semantic core-product auditor for Hebrew supermarket titles.

You are given a product core already selected by another semantic stage:
BASE + FINAL_MODIFIER.

Decide two things independently.

1. BASE IDENTITY:
- complete_product: BASE by itself is a sufficiently specific ordinary
  supermarket product identity. A shopper saying only BASE would know WHAT
  product category to buy without needing the modifier to choose between
  materially different product categories.
- incomplete_family: BASE is an umbrella/broad family. A shopper saying only
  BASE would still need to know the modifier before they could know WHAT
  concrete product category is intended.

IMPORTANT: "BASE can itself appear on a shopping list" is NOT sufficient for
complete_product. Distinguish a coherent product class from an umbrella family.
If BASE covers materially different product classes, it remains incomplete until
a category-defining modifier resolves which class is intended. Conversely, a
coherent product class may have many ordinary variants; variety alone does not
make BASE incomplete.

For BASE + FINAL_MODIFIER, use a replacement test: replace FINAL_MODIFIER with
another plausible value. If the shopper is still buying the same product class and
only a property/version changes, it is an ATTRIBUTE. If changing it changes WHAT
product class is being bought, it is core-defining PRODUCT information.

2. MODIFIER ROLE:
- attribute: the modifier specifies WHICH version, variety, flavor, property,
  preparation, processing state, formulation, form, or other specification
  of an already identified BASE.
- core_defining: the modifier is necessary to identify WHAT concrete product
  category is being requested. It changes the product identity rather than
  merely selecting a version of an already identified product.

CRITICAL:
A modifier is not an ATTRIBUTE merely because it is grammatically an adjective,
and it is not PRODUCT merely because the combined phrase is common, searchable,
commercially distinctive, or printed together in catalogs.

Use this decisive test:
"If the shopper said only BASE, would the listener know WHAT concrete product
category to buy, without having to infer which materially different category
the shopper meant?"

- YES -> BASE is complete_product. A following modifier normally specifies
  WHICH VERSION/VARIETY/STATE/etc. and is therefore attribute information.
- NO -> BASE is incomplete_family. The modifier is needed for PRODUCT identity.

Do not confuse "generic" with "incomplete". A broad but valid product such as
a staple category can still be a complete product identity when the modifier
only selects a normal variety. What matters is whether the modifier is needed
to identify the concrete category, not whether alternatives exist.

For relational/prepositional phrases, evaluate the complete relation as
one semantic unit before deciding the boundary. If the selected core ends in
a relational connector but the following complement completes that relation,
do not treat the connector as part of PRODUCT merely because it is adjacent
to a noun. Re-test the base before the complete relational phrase.
For preparation/processing/state words, apply the same WHAT-vs-WHICH test.
A processing/state descriptor is normally a specification of an already identified
product unless removing it changes the underlying product referent itself.
For varieties/subtypes, apply the same test.

COMPOUND NOUN SAFETY:
Do not strip a word from a multi-word product name merely because the remaining
prefix is sometimes used informally. Ask whether the remaining prefix still
denotes the same concrete product referent. If the added noun identifies the
substance/species/object/category that makes the product referent concrete,
keep it in PRODUCT. The existence of a shorthand use is not enough to make the
prefix complete. Do not assume every adjective
is an attribute and do not assume every noun/adjective combination is PRODUCT.

Do not use product names, dictionaries, phrase lists, regexes, or benchmark-specific
rules. Evaluate only the supplied BASE and FINAL_MODIFIER in the current request.
"""

        prompt = f"""CURRENT TITLE: {body}

SELECTED CORE: {core}
BASE: {base}
FINAL MODIFIER: {modifier}

Return the two independent semantic classifications."""
        try:
            audit = self._chat_json(
                [{"role": "user", "content": prompt}],
                system_prompt=system,
                response_schema=schema,
            )
            if (
                audit.get("modifier_role") == "attribute"
                and audit.get("base_identity") == "complete_product"
            ):
                # Require a second, differently framed identity judgment before
                # shortening PRODUCT. This prevents one broad interpretation of
                # BASE from contracting a category-defining modifier.
                base_schema = {
                    "name": "base_only_identity_check",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "identity": {
                                "type": "string",
                                "enum": ["complete_product", "incomplete_family"]
                            }
                        },
                        "required": ["identity"],
                        "additionalProperties": False
                    }
                }
                base_system = IDENTITY_CONTRACT + """You are an independent supermarket product-identity judge.

Judge BASE alone, with no modifier supplied.

`complete_product` means a shopper saying only BASE has identified a
concrete supermarket product category. The listener knows WHAT product
category to buy, even though ordinary variants may exist.

`incomplete_family` means BASE is only an umbrella/family term and the listener
would still need another category-defining word to know WHAT concrete product
is intended.

Do not decide based on whether BASE can ever appear on a shopping list.
Do not decide based on grammar, common phrases, catalog wording,
searchability, or commercial usage.

Use only this identity question:
"If someone says only BASE, do I know the concrete product category they want,
or would I still need another word to choose between materially different
product categories?"

Return only the identity classification.
"""
                try:
                    base_check = self._chat_json(
                        [{"role": "user", "content": f"BASE ONLY: {base}"}],
                        system_prompt=base_system,
                        response_schema=base_schema,
                    )
                    if base_check.get("identity") == "complete_product":
                        return base
                except Exception:
                    pass
        except Exception:
            pass

        # Final referent-level boundary adjudication.  Earlier boundary passes can
        # agree on the same wrong interpretation, especially for application
        # phrases and food formulations.  This last pass evaluates every
        # possible prefix of the current core against the complete suffix and
        # asks the actual shopper-identification question.  It is semantic only:
        # no vocabulary, brand list, regex, or benchmark-specific exception is
        # used.
        core_tokens = core.split()
        if len(core_tokens) >= 2:
            final_boundary_schema = {
                "name": "final_referent_boundary_adjudication",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "boundary": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": len(core_tokens),
                        }
                    },
                    "required": ["boundary"],
                    "additionalProperties": False,
                },
            }
            final_candidates = "\n".join(
                f"{i}: BASE='{ ' '.join(core_tokens[:i]) }' | "
                f"ADDITION='{ ' '.join(core_tokens[i:]) }'"
                for i in range(1, len(core_tokens) + 1)
            )
            final_boundary_system = IDENTITY_CONTRACT + """
You are the final referent-level PRODUCT boundary adjudicator.

The current PRODUCT candidate may be too long or too short. Evaluate every
internal boundary and choose the EARLIEST boundary that still identifies the
actual concrete supermarket product the shopper is asking for.

Use the shopper-information test, not phrase familiarity:

1. Remove the ADDITION completely.
2. Ask what concrete product the listener would understand the shopper to buy.
3. Put the ADDITION back.
4. Ask whether it merely specifies a version/property of that same product,
   or whether it identifies a different concrete product category/referent
   that the shopper could reasonably mean by the full expression.

ATTRIBUTE information includes flavor, variety, subtype, formulation,
processing/state, texture, color, material, size, audience, application
condition/target, preparation, and other properties WHEN the BASE already
identifies the product being bought.

PRODUCT information includes an addition when the BASE is an umbrella/family
or an insufficient referent, OR when the full addition changes the concrete
product category itself rather than merely specifying a version of the BASE.

PRODUCT-CLASS TEST:
Do not equate "a valid supermarket category" with "a sufficiently specific
shopping target". If BASE is an umbrella that contains materially different
product classes, the addition that selects the class belongs to PRODUCT. If BASE
already names one coherent product class, a normal variety/property remains an
ATTRIBUTE.

REPLACEMENT TEST:
Replace ADDITION with another plausible value. If the shopper would still be
buying the same product class and only the version/property changes, ADDITION is
an ATTRIBUTE. If changing ADDITION changes WHAT product class is being bought,
ADDITION is product-defining.

APPLICATION/RELATIONAL PHRASES REQUIRE SPECIAL CARE:
Do not classify every "for X" phrase as an attribute and do not classify every
"for X" phrase as PRODUCT. Ask what the shopper would understand as the
product referent. A target/condition such as a hair condition or skin
condition can specify a version of an already identified product. But an
application-specific product category can itself be part of WHAT product is
being requested. Decide from the completed referent and the information
needed to identify what is being bought.

COMPOUND IDENTITY:
Do not strip a noun or component that completes the concrete referent. Conversely,
do not keep a modifier merely because the complete phrase is natural or common
in retail. The question is whether removing it changes WHAT product category
the listener would identify, rather than merely WHICH version they would choose.

CONTRASTIVE CALIBRATION:
- A broad family may need a following category-defining word to identify the
  product, while a normal product category can have varieties without absorbing
  those varieties into PRODUCT.
- A product can be followed by a flavor, variety, processing state, or target
  and still retain the shorter PRODUCT.
- An application phrase can be either category-defining or merely a use/condition
  attribute; determine which by the concrete referent, not by the preposition.
- The same grammatical construction may therefore produce different boundaries
  in different semantic contexts.

Do not use product names, dictionaries, regexes, phrase lists, or benchmark
exceptions. Return only the earliest semantically complete PRODUCT boundary.
"""
            final_prompt = (
                f"FULL TITLE: {product_name}\n"
                f"CURRENT CORE: {core}\n\n"
                f"ALL INTERNAL BOUNDARIES:\n{final_candidates}\n\n"
                "Choose the earliest boundary that still identifies WHAT concrete "
                "product is being requested."
            )
            votes=[]
            for framing in (
                "",
                "\nIndependently reconsider the BASE-versus-ADDITION referent. "
                "Do not copy the current core simply because it is already selected.",
            ):
                try:
                    rr=self._chat_json(
                        [{"role":"user","content":final_prompt+framing}],
                        system_prompt=final_boundary_system,
                        response_schema=final_boundary_schema,
                    )
                    b=rr.get("boundary")
                    if isinstance(b,int) and 1 <= b <= len(core_tokens):
                        votes.append(b)
                except Exception:
                    pass
            if len(votes)==2 and votes[0]==votes[1]:
                core=" ".join(core_tokens[:votes[0]])


        # Final pairwise referent-vs-specification gate.
        # Unlike the earlier boundary prompts that choose among many candidates,
        # this stage evaluates ONE boundary at a time.  It explicitly separates
        # (a) whether the left side is already a complete product referent from
        # (b) whether the right side merely selects a property/version of it.
        # This prevents a familiar retail expression from winning simply because
        # the model sees the whole phrase as a product name.
        body_for_gate = product_name.strip()
        if known_brand and known_brand.strip() and body_for_gate.startswith(known_brand.strip()):
            body_for_gate = body_for_gate[len(known_brand.strip()):].lstrip()
            for sep in ("-", "–", "—", ":"):
                if body_for_gate.startswith(sep):
                    body_for_gate = body_for_gate[len(sep):].lstrip()
                    break

        gate_tokens = body_for_gate.split()
        gate_lexical = []
        for tok in gate_tokens:
            if re.search(r"\d", tok):
                break
            gate_lexical.append(tok)

        if len(gate_lexical) >= 2:
            # Final boundary authority is deliberately decomposed into two
            # independent semantic judgments.  The old coupled judge could
            # let "this is a familiar product phrase" dominate both questions.
            # Here LEFT completeness and RIGHT specification are evaluated
            # separately, then reconciled deterministically.
            left_schema = {
                "name": "left_product_referent_judge",
                "strict": True,
                "schema": {
                    "complete": {
                        "type": "string",
                        "enum": ["yes", "no"],
                    },
                },
                "required": ["complete"],
                "additionalProperties": False,
            }
            right_schema = {
                "name": "right_product_specification_judge",
                "strict": True,
                "schema": {
                    "is_specification": {
                        "type": "string",
                        "enum": ["yes", "no"],
                    },
                    "semantic_axis": {
                        "type": "string",
                        "enum": [
                            "טעם", "סוג", "ריח", "צבע", "חומר", "קהל יעד",
                            "גודל", "מידה", "צורה", "כמות", "אחוז שומן",
                            "מספר יחידות", "other"
                        ],
                    },
                },
                "required": ["is_specification", "semantic_axis"],
                "additionalProperties": False,
            }

            left_system = IDENTITY_CONTRACT + """You are an independent
semantic PRODUCT-REFERENT judge.

Evaluate ONLY LEFT. The suffix is intentionally hidden from you.
Do not infer missing words from the original title, product catalog knowledge,
or a familiar longer retail expression.

Would a normal shopper/listener know WHAT product they are being asked to buy
if they heard only LEFT on an ordinary shopping list?

Use this exact semantic test:
- COMPLETE means LEFT itself identifies the ordinary product category/referent.
  It may have many varieties, flavors, sizes, formulations, or processing states;
  those differences do not by themselves make LEFT incomplete.
- INCOMPLETE means LEFT is only an umbrella/family reference, so the listener
  cannot know which materially different product category is meant without the
  following words.

Do NOT treat "there are many kinds of LEFT" as evidence of incompleteness.
Instead distinguish VARIANTS of one product class from an UMBRELLA FAMILY that
contains materially different product classes.

Apply this exact sequence:
1. LEFT alone: could a shopper select the intended product class without another
   category-defining word?
2. If LEFT covers several materially different product classes, it is incomplete.
3. If LEFT already names one coherent product class, it is complete even though
   it may have ordinary variants.
4. For the boundary LEFT + RIGHT, mentally replace RIGHT with another ordinary
   value. If the same product class remains and only its version/property changes,
   RIGHT is a specification. If the replacement changes WHAT product class is being
   bought, RIGHT is product-defining.

Do not let the fact that LEFT is a valid supermarket category override this test.
The question is whether it is sufficiently specific as a real shopping target,
not whether the word can be used as a category label.

Use the shopper's requested product identity, not catalog naming.

Important:
- "LEFT can be purchased" is not enough to make it complete.
- "LEFT has varieties" is not enough to make it incomplete.
- Do not use phrase familiarity, searchability, grammar, dictionaries, or
  benchmark-specific rules.
- Return only the JSON decision.
"""

            right_system = IDENTITY_CONTRACT + """You are an independent
semantic PRODUCT-SPECIFICATION judge.

LEFT is already supplied as a candidate product. RIGHT is the complete suffix
after LEFT before quantity.

Determine whether RIGHT is a specification/property of LEFT rather than a word
needed to identify WHAT product LEFT is.

A RIGHT side is a specification when it answers a question such as:
- what it tastes like -> טעם
- which variety/subtype/formulation/preparation/processing/state -> סוג
- what it smells like -> ריח
- what color/material/size/dimension/shape -> the corresponding axis
- who it is for -> קהל יעד
- what application/condition it targets -> סוג
- how much/how many -> the corresponding quantity axis

Crucial counterfactual:
Hold LEFT fixed and replace RIGHT with another plausible value. If LEFT remains
the same ordinary supermarket product category and only its property/version
changes, RIGHT is a specification. This includes a flavor or ingredient that
serves as the sensory identity of the same base product.

Only classify RIGHT as identity completion when removing RIGHT leaves an
umbrella/family rather than one coherent product class. Do not call it identity
completion merely because the base has many variants.

Use the replacement test before deciding: replace RIGHT with another plausible
value. If the shopper is still buying the same product class and only a property
or version changes, RIGHT is a specification. If the replacement changes WHAT
product class the shopper is buying, RIGHT is part of PRODUCT identity.

Evaluate RIGHT semantically in relation to LEFT. Do not use retail/catalog
phrase familiarity, searchability, grammar, dictionaries, or benchmark-specific
rules. Do not decide merely because RIGHT is a noun or because the complete
phrase is commonly sold under one name.

Return only the JSON decision.
"""

            gate_boundaries = []
            for boundary in range(1, len(gate_lexical)):
                left = " ".join(gate_lexical[:boundary])
                right = " ".join(gate_lexical[boundary:])
                # True isolation: the LEFT judge must not see the suffix or
                # the full product body. Otherwise the familiar complete retail
                # expression can bias the supposedly independent referent test.
                left_context = f"LEFT ONLY: {left}\n"
                right_context = (
                    f"LEFT PRODUCT: {left}\n"
                    f"RIGHT SUFFIX: {right}\n"
                )

                left_votes = []
                right_votes = []
                framings = (
                    "",
                    "\nRecompute the LEFT referent independently from scratch.",
                )
                for framing in framings:
                    try:
                        lr = self._chat_json(
                            [{"role": "user", "content": left_context + framing}],
                            system_prompt=left_system,
                            response_schema=left_schema,
                        )
                        if lr.get("complete") in {"yes", "no"}:
                            left_votes.append(lr["complete"])
                    except Exception:
                        pass
                    try:
                        rr = self._chat_json(
                            [{"role": "user", "content": right_context + framing}],
                            system_prompt=right_system,
                            response_schema=right_schema,
                        )
                        if (
                            rr.get("is_specification") in {"yes", "no"}
                            and isinstance(rr.get("semantic_axis"), str)
                        ):
                            right_votes.append(rr["is_specification"])
                    except Exception:
                        pass

                if (
                    len(left_votes) == 2
                    and len(right_votes) == 2
                    and left_votes[0] == "yes"
                    and left_votes[1] == "yes"
                    and right_votes[0] == "yes"
                    and right_votes[1] == "yes"
                ):
                    gate_boundaries.append(boundary)

            if gate_boundaries:
                core = " ".join(gate_lexical[:min(gate_boundaries)])

        return core

    def allocate_after_core(
        self,
        product_name: str,
        core_product: str,
        known_brand: str = "",
    ) -> dict[str, Any]:
        """Allocate semantic attributes as atomic source spans after a fixed core.

        The allocator first identifies semantic attribute spans and then runs a
        second independent span audit.  The audit is specifically responsible
        for detecting adjacent expressions that have different meanings.  This
        prevents a physical amount from absorbing a neighboring percentage or
        another independent attribute.
        """
        source = product_name.strip()
        core = core_product.strip()
        if not source or not core:
            return {"attributes": []}

        # The allocator is strictly post-core. Give the model only the exact
        # source suffix after the fixed PRODUCT boundary, rather than the full
        # title. This prevents BRAND and PRODUCT text from leaking into the
        # attribute partition and makes the source-span contract unambiguous.
        core_start = source.find(core)
        if core_start < 0:
            return {"attributes": []}
        remainder = source[core_start + len(core):].lstrip()

        schema = {
            "name": "post_core_atomic_attributes",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string"},
                            },
                            "required": ["text", "kind"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }

        system = (
            "You are Baskit's semantic attribute allocator.\n\n"
            "The PRODUCT boundary is FIXED. Never change it.\n\n"
            "Your job is to partition ONLY the exact source text after PRODUCT "
            "into the smallest set of COMPLETE SEMANTIC ATTRIBUTE SPANS.\n\n"
            "ATOMIC-SPAN RULE:\n"
            "Two adjacent expressions must be separate attributes when they "
            "answer different semantic questions, even if there is only a space "
            "between them and even if both are numeric.\n\n"
            "NUMERIC SEMANTICS:\n"
            "- A percentage describing fat content is `אחוז שומן`.\n"
            "- A physical product/package measurement with its unit is `כמות`.\n"
            "- These are DIFFERENT semantic attributes. Never combine a fat "
            "percentage with a mass/volume amount into one span.\n"
            "- A number and its physical unit belong together as ONE `כמות` "
            "span. The unit does not include a preceding percentage or another "
            "attribute.\n"
            "- A count of separate objects is `מספר יחידות`.\n\n"
            "OTHER KINDS:\n"
            "`טעם` = sensory flavor ONLY: a property perceived by tasting; use this kind only when the attribute answers the question \"what does this product taste like?\". If the attribute primarily describes preparation, cooking, roasting, baking, smoking, freezing, slicing, processing, preservation, foaming, or another physical transformation/state, classify it as `סוג` even if that process also affects taste. Secondary sensory consequences do not turn a processing descriptor into flavor. `צבע` = literal visual appearance/color, including color adjectives applied to food or other products; a visual color remains `צבע` even when the product is edible. `סוג` = "
            "formulation/composition/preparation/processing state/categorical "
            "variant, subtype, variety, or non-sensory categorical version. A "
            "named variety/member of the same product class is `סוג`, not "
            "`טעם`, unless it actually answers what the product tastes like. "
            "Do not classify a named grain/rice/pasta variety as `טעם` merely "
            "because it is a food word; classify by the property it expresses. "
            "`גודל` = qualitative size; `מידה` = standardized "
            "dimension/fit; `חומר` = material; `קהל יעד` = intended human/animal audience or recipient. A body area, "
            "hair type, skin condition, or application target is NOT automatically "
            "`קהל יעד`; when it describes the product's intended application target "
            "or condition rather than who receives it, classify it as `סוג`.\n\n"
            "OUTPUT CONTRACT:\n"
            "Return exactly ONE JSON object and nothing else. The object must "
            "contain only the requested attribute list. Never repeat an attribute, "
            "never emit partial unit fragments, and never invent text that is not "
            "an exact contiguous substring of the source.\n\n"
            "SEMANTIC CARRIER RULE:\n"
            "Do NOT treat a relational phrase as one span merely because its words "
            "are grammatically connected. First separate the semantic carrier from "
            "the semantic value. A carrier is wording whose only job is to introduce "
            "or connect the property; it has no independent shopping meaning. If the "
            "following source words already name the actual attribute value, output "
            "the value and omit the carrier entirely. Never turn the carrier into a "
            "second attribute and never output it as unclassified merely to preserve "
            "source coverage.\n"
            "For example, when a product is described using wording equivalent to "
            "'with scent X', the semantic result is X as kind ריח; the relational "
            "wording that introduces the scent is omitted. The same reasoning applies "
            "to other semantic relations: identify the real value first, then ask "
            "whether the surrounding relational wording contributes any independent "
            "shopper-relevant property. If it does not, drop it.\n"
            "This is a semantic-function decision, not a vocabulary list. Do not "
            "memorize or hard-code connector words, phrases, products, brands, or "
            "examples.\n\n"
            "SOURCE INTEGRITY:\n"
            "Every returned text must be an exact contiguous substring of the "

            "source after PRODUCT. Preserve source wording exactly. Do not "
            "invent, normalize, concatenate, or delete text.\n\n"
            "CRITICAL EXAMPLE OF THE GENERAL RULE:\n"
            "When the remaining source contains a percentage followed by a "
            "physical amount, evaluate the percentage and the physical amount "
            "as separate semantic expressions. Do not return them as one span.\n\n"
            "Return JSON only."
        )

        prompt = (
            f"FIXED PRODUCT: {core}\n"
            f"REMAINING SOURCE AFTER PRODUCT: {remainder}\n\n"
            "Partition ONLY the remaining source text shown above into atomic "
            "semantic attributes. The fixed PRODUCT and any text before it are "
            "not part of the answer and must never appear in attributes. "
            "Keep semantically different adjacent attributes separate."
        )

        try:
            first = self._chat_json(
                [{"role": "user", "content": prompt}],
                system_prompt=system,
                response_schema=schema,
            )
        except Exception:
            return {"attributes": []}

        attrs = first.get("attributes") if isinstance(first, dict) else None
        if not isinstance(attrs, list):
            return {"attributes": []}

        # Independent audit of the proposed spans. It receives no product
        # vocabulary and is allowed only to split/clarify spans, never to move
        # anything into PRODUCT.
        audit_schema = {
            "name": "attribute_span_audit",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string"},
                            },
                            "required": ["text", "kind"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }

        audit_prompt = (
            f"FULL SOURCE: {source}\n"
            f"FIXED PRODUCT: {core}\n"
            f"PROPOSED ATTRIBUTES: {json.dumps(attrs, ensure_ascii=False)}\n\n"
            "Audit the proposed attribute partition.\n"
            "Preserve every correct source span exactly. If one proposed span "
            "contains multiple semantically independent attributes, split it "
            "into separate exact contiguous source spans.\n"
            "Classify by the property the attribute actually denotes, not by associations with a food product. `טעם` requires sensory taste: "
            "the attribute must answer what the product tastes like. `צבע` means visual appearance/color; a visual color remains `צבע` even "
            "for edible products and does not become `טעם` merely because that color is associated with a flavor. A named variety/subtype/version "
            "is `סוג`, not `טעם`, "
"A processing/presentation descriptor is `סוג`, not `מידה`. A relational composition such as an ingredient/addition can also be `סוג` "
"when it describes the product formulation rather than sensory taste.\n"
            "In particular, a fat-content percentage and a physical package "
            "amount are two attributes, not one quantity span.\n"
            "Do not merge adjacent attributes merely because they are both "
            "numeric or adjacent in the source.\n"
            "Do not modify PRODUCT."
        )

        try:
            audited = self._chat_json(
                [{"role": "user", "content": audit_prompt}],
                system_prompt=system,
                response_schema=audit_schema,
            )
            audited_attrs = audited.get("attributes")
            if isinstance(audited_attrs, list):
                attrs = audited_attrs
        except Exception:
            pass

        # Final independent adjudication.  This pass is deliberately
        # responsible for BOTH span boundaries and attribute taxonomy.  It
        # receives the original source and the fixed product, rather than
        # inheriting a potentially incorrect span interpretation from the
        # first allocator.  It cannot modify PRODUCT.
        adjudication_schema = {
            "name": "final_attribute_adjudication",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string"},
                            },
                            "required": ["text", "kind"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }

        adjudication_system = (
            "You are the final semantic adjudicator for Baskit attributes.\\n\\n"
            "PRODUCT IS FIXED. Never change, extend, shorten, or reinterpret PRODUCT.\\n"
            "Only analyze the source text AFTER the fixed PRODUCT.\\n\\n"
            "Reconstruct the attribute spans from the SOURCE itself. The proposed "
            "attributes are evidence only and may be wrong. Do not preserve a bad "
            "span merely because it was proposed. Every returned span must be an "
            "exact contiguous substring of SOURCE, in source order, and every "
            "meaningful source expression after PRODUCT must be represented exactly once.\\n\\n"
            "SEMANTIC TAXONOMY: classify what the attribute MEANS, not what the "
            "word resembles grammatically.\\n"
            "- `טעם`: sensory taste/flavor. Ask: 'What does the product taste like?' "
            "Use this when the modifier communicates the product's intended flavor "
            "profile, including when that flavor is expressed by the name of an "
            "ingredient or flavor source.\\n"
            "- `צבע`: literal visual color/appearance. Ask: 'What color does it look like?' "
            "A food-related word is still `צבע` when it describes visual color rather "
            "than taste.\\n"
            "- `סוג`: formulation, composition, preparation, processing/state, "
            "presentation, texture/formulation, subtype, variety, or other categorical "
            "version. Sliced/cut/presented descriptors and formulation/texture descriptors "
            "belong here, not `מידה` and not `טעם` unless they actually describe taste.\\n"
            "- `מידה`: standardized dimensions or fit ONLY. It is not a fallback for "
            "processing, presentation, texture, or form.\\n"
            "- `גודל`: qualitative size.\\n"
            "- `חומר`: material.\\n"
            "- `קהל יעד`: intended audience.\\n"
            "- `מספר יחידות`: count of separate objects/packages.\\n"
            "- `כמות`: one physical amount consisting of a number and its physical unit. "
            "THE NUMBER AND UNIT ARE ONE SPAN. Never split them into separate attributes. "
            "For example, any source expression of the form number + physical mass/volume "
            "unit is one `כמות` attribute.\\n"
            "- `אחוז שומן`: a percentage that semantically represents fat content.\\n\\n"
            "IMPORTANT: semantic ambiguity must be resolved from the relationship between "
            "the ATTRIBUTE and the PRODUCT. An ingredient/source word can function as a "
            "flavor when it communicates the product's sensory flavor profile; do not "
            "automatically classify ingredient nouns as `סוג`. Conversely, a texture or "
            "formulation descriptor is not a flavor merely because it could have sensory "
            "associations.\\n\\n"
            "Before returning JSON, perform two checks: (1) every number + physical unit "
            "that expresses package/product amount remains one contiguous `כמות` span; "
            "(2) every non-numeric attribute is classified by the semantic question it "
            "answers. Do not use memorized product names or benchmark-specific rules."
        )

        adjudication_prompt = (
            f"SOURCE: {source}\n"
            f"FIXED PRODUCT: {core}\n"
            f"PROPOSED ATTRIBUTES (may be wrong): {json.dumps(attrs, ensure_ascii=False)}\n\n"
            "Rebuild the final attribute list from SOURCE. Correct both boundaries and kinds "
            "where necessary. Return JSON only."
        )

        try:
            final = self._chat_json(
                [{"role": "user", "content": adjudication_prompt}],
                system_prompt=adjudication_system,
                response_schema=adjudication_schema,
            )
            final_attrs = final.get("attributes")
            if isinstance(final_attrs, list):
                attrs = final_attrs
        except Exception:
            pass

        # Axis-first semantic adjudication.  The previous pass asked for the
        # final taxonomy directly, which can cause a model to anchor on the
        # surface word.  This pass first identifies WHAT DIMENSION the
        # attribute changes relative to PRODUCT, then maps that dimension to
        # Baskit's taxonomy.  This is intentionally generic and source-grounded.
        axis_schema = {
            "name": "attribute_semantic_axis",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "axis": {
                                    "type": "string",
                                    "enum": [
                                        "taste", "color", "formulation",
                                        "processing", "variety", "dimension",
                                        "size", "material", "quantity",
                                        "unit_count", "fat_percentage",
                                        "audience", "scent", "other"
                                    ],
                                },
                            },
                            "required": ["text", "axis"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }

        axis_system = (
            "You are Baskit's final semantic attribute adjudicator. PRODUCT IS FIXED. "
            "Never change PRODUCT. Determine the semantic meaning of each remaining "
            "SOURCE span from its relationship to PRODUCT.\n\n"

            "CORE METHOD: first ask what PROPERTY of PRODUCT the span changes. Then "
            "map that property to exactly one axis. Never classify from the word alone.\n\n"

            "AXES:\n"
            "taste = sensory flavor; what the product tastes like. An ingredient/source "
            "noun may be taste when it is the carrier of the intended flavor.\n"
            "scent = smell/aroma/fragrance.\n"
            "color = literal visual appearance/color.\n"
            "material = physical material the object is made from.\n"
            "formulation = composition/recipe/medium/texture/consistency.\n"
            "processing = preparation/preservation/processing/presentation state.\n"
            "variety = categorical subtype/variety/style/version.\n"
            "dimension = standardized dimension/fit/size system.\n"
            "size = qualitative size.\n"
            "shape = literal geometry.\n"
            "quantity = physical amount expressed by number + physical unit as ONE span.\n"
            "unit_count = count of separate units/objects/packages.\n"
            "fat_percentage = percentage expressing fat content.\n"
            "audience = intended user/recipient.\n"
            "APPLICATION TARGET / CONDITION: A phrase describing a body area, "
            "hair type, skin condition, application area, or intended target is "
            "not an audience merely because it is introduced relationally. When "
            "it selects a use-specific version of the fixed product, classify it "
            "as formulation/type. Audience is reserved for WHO receives or uses "
            "the product, such as women, men, babies, children, or animals.\n"
            "other = none of these.\n\n"

            "MOST IMPORTANT CONTRAST: TASTE vs FORMULATION/TYPE.\n"
            "Use taste when substituting the span would change the intended sensory "
            "flavor of the same product. Examples: yogurt+strawberry, soup powder+"
            "mushroom, herbal tea+chamomile, wafer+hazelnut, cookies+chocolate, "
            "cookies+butter, ice cream+vanilla.\n"
            "A named variety, cultivar, grain/plant variety, subtype, or categorical "
            "version is NOT taste merely because it is associated with a particular "
            "food or flavor. If it answers WHICH variety/version of the product rather "
            "than WHAT it tastes like, classify it as variety/type.\n"
            "A named grain/cultivar or other categorical variety identifies which "
            "member of a product family is wanted. It does not answer what the "
            "product tastes like. For a grain product followed by a named grain "
            "variety, the variety axis is `variety`/`סוג`, not taste; generalize "
            "this to named cultivars and other categorical varieties.\n"
            "Use formulation/type when substituting the span changes composition, "
            "texture, preparation, processing, medium, or categorical version. Examples: "
            "hummus+with tahini, tuna+in oil, mayonnaise+light, body soap+creamy, "
            "coffee+ground, coffee+instant, peas+frozen, pasta+spaghetti.\n"
            "The fact that an ingredient noun appears does NOT force formulation/type; "
            "its semantic role can be flavor. Conversely, a sensory adjective does NOT "
            "force taste if it actually describes texture/formulation.\n\n"

            "OTHER CONTRASTS:\n"
            "color is visual, even for food; do not infer taste from color associations.\n"
            "scent is smell, not taste and not formulation.\n"
            "material is what an object is physically made from, not its product type.\n"
            "shape is literal geometry; slicing/freezing/foaming/creamy texture are "
            "processing/formulation, not shape.\n"
            "size is qualitative; dimension is standardized fit/measurement; quantity "
            "is amount of contents; unit_count counts separate objects.\n"
            "audience is who it is for.\n\n"

            "COUNTERFACTUAL TEST: Hold PRODUCT fixed and replace the attribute with "
            "another value. What aspect of PRODUCT would change? If flavor changes -> "
            "taste. If smell changes -> scent. If visual color changes -> color. If "
            "material changes -> material. If texture/composition changes -> formulation. "
            "If processing/presentation changes -> processing. If variety/version changes "
            "-> variety. If dimensions/fit change -> dimension. If qualitative size changes "
            "-> size. If physical amount changes -> quantity. If item count changes -> "
            "unit_count. If intended user changes -> audience. If geometry changes -> shape.\n\n"

            "Do not memorize any example. Generalize the semantic relationship to unseen "
            "products and domains.\n\n"

            "SOURCE INTEGRITY: every returned text is an exact contiguous substring of "
            "SOURCE, in source order. A number and its physical unit are one quantity span."
        )

        axis_prompt = (
            f"SOURCE: {source}\n"
            f"FIXED PRODUCT: {core}\n"
            f"CURRENT ATTRIBUTES (evidence only): {json.dumps(attrs, ensure_ascii=False)}\n\n"
            "For every attribute, first determine internally which question it answers "
            "(taste, smell, color, material, audience, size, dimension, shape, quantity, "
            "unit count, fat percentage, or formulation/type). Then apply the hard "
            "boundaries in the system instructions. Pay special attention to the "
            "difference between sensory flavor and formulation/texture: an ingredient "
            "word may denote flavor when it communicates the product's intended taste, "
            "while a texture/formulation descriptor remains type. A processing "
            "operation or state (such as cooking, roasting, grilling, baking, frying, "
            "slicing, smoking, drying, freezing, or similar preparation) is also "
            "processing/type even if it has a recognizable sensory consequence; ask "
            "whether the word describes WHAT WAS DONE TO THE PRODUCT rather than WHAT "
            "THE PRODUCT TASTES LIKE. Also distinguish "
            "WHO the product is for (audience) from WHAT BODY AREA, HAIR TYPE, SKIN "
            "CONDITION, or APPLICATION TARGET it is intended for; the latter is a "
            "product-version/use attribute, not audience. Reconstruct spans from "
            "SOURCE if needed. Return JSON only."
        )

        try:
            axis_result = self._chat_json(
                [{"role": "user", "content": axis_prompt}],
                system_prompt=axis_system,
                response_schema=axis_schema,
            )
            axis_attrs = axis_result.get("attributes")
            if isinstance(axis_attrs, list):
                axis_to_kind = {
                    "taste": "טעם",
                    "color": "צבע",
                    "formulation": "סוג",
                    "processing": "סוג",
                    "variety": "סוג",
                    "dimension": "מידה",
                    "size": "גודל",
                    "material": "חומר",
                    "quantity": "כמות",
                    "unit_count": "מספר יחידות",
                    "fat_percentage": "אחוז שומן",
                    "audience": "קהל יעד",
                    "scent": "ריח",
                    "shape": "צורה",
                }
                mapped = []
                for item in axis_attrs:
                    if not isinstance(item, dict):
                        continue
                    text_value = item.get("text")
                    axis = item.get("axis")
                    if isinstance(text_value, str) and isinstance(axis, str):
                        mapped.append({
                            "text": text_value,
                            "kind": axis_to_kind.get(axis, "סוג"),
                        })
                if mapped:
                    attrs = mapped
        except Exception:
            pass

        # Dedicated variety-vs-taste adjudication.
        # This is intentionally a separate semantic question because a single
        # taxonomy pass can anchor on food vocabulary and mistake a named
        # product variety for a sensory flavor.  It never changes PRODUCT or
        # source spans; it only adjudicates the semantic axis of the already
        # allocated attribute spans.
        variety_schema = {
            "name": "variety_vs_taste_adjudication",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "decision": {
                                    "type": "string",
                                    "enum": ["taste", "variety", "other"],
                                },
                            },
                            "required": ["text", "decision"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }

        variety_system = (
            "You are a semantic property judge for Baskit. PRODUCT IS FIXED. "
            "Do not change PRODUCT and do not invent or alter source text.\n\n"
            "Your narrow task is to distinguish sensory FLAVOR from a named "
            "PRODUCT VARIETY / SUBTYPE / CATEGORICAL VERSION.\n\n"
            "TASTE means the attribute answers: 'What does this already-identified "
            "product taste like?' It describes the intended sensory flavor profile.\n\n"
            "VARIETY means the attribute answers: 'Which member, variety, subtype, "
            "or categorical version of this already-identified product is wanted?' "
            "It is still the same product category, but a different member/version "
            "within that category. Named cultivars, grain varieties, pasta shapes "
            "or other categorical members belong here when they identify which "
            "member is wanted rather than communicating flavor.\n\n"
            "CRITICAL TEST: hold PRODUCT fixed. Imagine replacing the attribute "
            "with another member of the same product category. If the replacement "
            "selects a different member/variety/version while PRODUCT remains the "
            "same category, choose VARIETY. If the replacement changes the sensory "
            "flavor of the same category, choose TASTE.\n\n"
            "Do NOT decide from whether the word is a food ingredient, noun, "
            "adjective, or something edible. Decide from its semantic relationship "
            "to PRODUCT. A named grain/plant/cultivar/product variety is not taste "
            "merely because it can have a characteristic flavor. Conversely, a "
            "flavor source can be taste when it tells the shopper what the product "
            "is intended to taste like.\n\n"
            "Return one decision for every supplied attribute. Do not change spans."
        )

        # Only attributes whose current semantic kind is TASTE or TYPE are
        # eligible for this narrow adjudicator. Objective dimensions such as
        # quantity, fat percentage, color, material, audience, etc. have already
        # been resolved by the broader taxonomy and must not be reinterpreted by
        # a judge whose question is specifically taste-vs-variety.
        variety_candidates = [
            item for item in attrs
            if isinstance(item, dict)
            and item.get("kind") in {"טעם", "סוג"}
        ]

        variety_prompt = (
            f"SOURCE: {source}\n"
            f"FIXED PRODUCT: {core}\n"
            f"ATTRIBUTES TO JUDGE: {json.dumps(variety_candidates, ensure_ascii=False)}\n\n"
            "Judge ONLY the supplied candidates. Do not reinterpret or mention "
            "attributes that were not supplied. For each candidate, independently "
            "decide whether its semantic dimension is sensory taste, product "
            "variety/subtype, or neither. Use the replacement/member test above. "
            "Return JSON only."
        )

        try:
            variety_result = self._chat_json(
                [{"role": "user", "content": variety_prompt}],
                system_prompt=variety_system,
                response_schema=variety_schema,
            )
            variety_attrs = variety_result.get("attributes")
            if isinstance(variety_attrs, list):
                decisions = {
                    item.get("text"): item.get("decision")
                    for item in variety_attrs
                    if isinstance(item, dict)
                    and isinstance(item.get("text"), str)
                    and item.get("decision") in {"taste", "variety"}
                }
                if decisions:
                    refined = []
                    for item in attrs:
                        if not isinstance(item, dict):
                            continue
                        text_value = item.get("text")
                        if text_value in decisions:
                            decision = decisions[text_value]
                            item = dict(item)
                            if decision == "variety":
                                item["kind"] = "סוג"
                            elif decision == "taste":
                                item["kind"] = "טעם"
                        refined.append(item)
                    attrs = refined
        except Exception:
            pass


        # Final independent processing-vs-taste adjudication.
        # This runs after all broader taxonomy passes because processing
        # descriptors can be incorrectly pulled toward taste when they have
        # obvious sensory consequences.  It can change ONLY the kind of an
        # existing attribute span; PRODUCT and source spans remain fixed.
        process_schema = {
            "name": "processing_vs_taste_adjudication",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "axis": {
                                    "type": "string",
                                    "enum": ["taste", "processing", "other"],
                                },
                            },
                            "required": ["text", "axis"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }

        process_system = (
            "You are an independent semantic property adjudicator for Baskit. "
            "PRODUCT IS FIXED. You may NOT change PRODUCT, attribute boundaries, "
            "or source text. Your only job is to distinguish TASTE from PROCESSING "
            "for the already allocated attribute spans.\n\n"
            "The key distinction is semantic, not sensory association:\n"
            "TASTE = the span tells the shopper WHAT THE PRODUCT TASTES LIKE. "
            "It describes the intended flavor profile of the already identified product.\n"
            "PROCESSING = the span tells the shopper WHAT WAS DONE TO THE PRODUCT, "
            "HOW IT WAS PREPARED/PRESERVED, or WHAT PHYSICAL PROCESS/STATE the product "
            "is in. This includes transformations of preparation, cooking, roasting, "
            "grilling, baking, frying, smoking, drying, freezing, slicing, cutting, "
            "foaming, or comparable processing/presentation states. A process can "
            "produce a taste or sensory consequence, but that consequence is NOT the "
            "meaning of the processing descriptor.\n\n"
            "USE THIS COUNTERFACTUAL:\n"
            "1. Hold the PRODUCT fixed.\n"
            "2. Ask whether the span answers 'What does it taste like?' or instead "
            "'What was done to it / how was it prepared or processed?'.\n"
            "3. If the latter is true, choose PROCESSING even if the operation can "
            "change taste, smell, texture, or appearance.\n"
            "4. Choose TASTE only when the span itself communicates the sensory flavor "
            "the shopper should expect, rather than an operation or state that produced it.\n\n"
            "Do not infer TASTE merely because an attribute is associated with a flavor. "
            "Do not infer PROCESSING merely because the attribute is an adjective. "
            "Determine the property expressed by the span in relation to PRODUCT.\n\n"
            "Return one axis for every supplied attribute. For attributes that are "
            "clearly neither taste nor processing, return OTHER. Never alter their "
            "existing kind. Do not memorize examples or use benchmark-specific rules."
        )

        # This adjudicator is intentionally restricted to the same ambiguous
        # taste/type space. It must never reinterpret independently established
        # dimensions such as fat percentage, quantity, color, material, etc.
        process_candidates = [
            item for item in attrs
            if isinstance(item, dict)
            and item.get("kind") in {"טעם", "סוג"}
        ]

        process_prompt = (
            f"SOURCE: {source}\n"
            f"FIXED PRODUCT: {core}\n"
            f"ATTRIBUTES: {json.dumps(process_candidates, ensure_ascii=False)}\n\n"
            "Judge ONLY the supplied candidates. Do not reinterpret or mention "
            "attributes that were not supplied. For every supplied candidate, "
            "decide whether its semantic meaning is TASTE, PROCESSING, or OTHER. "
            "Return JSON only."
        )

        try:
            process_result = self._chat_json(
                [{"role": "user", "content": process_prompt}],
                system_prompt=process_system,
                response_schema=process_schema,
            )
            process_attrs = process_result.get("attributes")
            if isinstance(process_attrs, list):
                process_decisions = {
                    item.get("text"): item.get("axis")
                    for item in process_attrs
                    if isinstance(item, dict)
                    and isinstance(item.get("text"), str)
                    and item.get("axis") in {"taste", "processing"}
                }
                if process_decisions:
                    refined = []
                    for item in attrs:
                        if not isinstance(item, dict):
                            continue
                        text_value = item.get("text")
                        if text_value in process_decisions:
                            item = dict(item)
                            item["kind"] = (
                                "סוג"
                                if process_decisions[text_value] == "processing"
                                else "טעם"
                            )
                        refined.append(item)
                    attrs = refined
        except Exception:
            pass

        # Narrow formulation/texture-vs-taste adjudication.
        # This is separate from processing-vs-taste because descriptors such as
        # creamy/foamy/texture-related formulations can be mistaken for flavor
        # even though they describe how the product is formulated or feels.
        formulation_schema = {
            "name": "formulation_vs_taste_adjudication",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "axis": {
                                    "type": "string",
                                    "enum": ["taste", "formulation", "other"],
                                },
                            },
                            "required": ["text", "axis"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["attributes"],
                "additionalProperties": False,
            },
        }
        formulation_system = (
            "You are a narrow semantic property adjudicator for Baskit. PRODUCT "
            "is fixed. Do not change PRODUCT, spans, or source text. Judge only "
            "whether each supplied TASTE/TYPE attribute means sensory FLAVOR or "
            "PRODUCT FORMULATION/TEXTURE.\n\n"
            "TASTE answers: 'What does the product taste like?' It communicates "
            "the intended sensory flavor profile.\n"
            "FORMULATION answers: 'What is the product made/formulated like, or "
            "what texture/consistency/form it has?' Texture, consistency, creaminess, "
            "foaming, thickness, composition, medium, and formulation are not taste "
            "unless the span itself communicates flavor.\n\n"
            "Do not infer taste from pleasant sensory associations. A texture or "
            "formulation descriptor can have a sensory experience without being a "
            "flavor. Conversely, an ingredient/flavor source can be TASTE when it "
            "communicates what the product is intended to taste like.\n"
            "Return OTHER for candidates that are neither. Do not reinterpret "
            "attributes outside the supplied candidates."
        )
        formulation_candidates=[
            item for item in attrs
            if isinstance(item,dict) and item.get("kind") in {"טעם","סוג"}
        ]
        formulation_prompt=(
            f"SOURCE: {source}\nFIXED PRODUCT: {core}\n"
            f"ATTRIBUTES TO JUDGE: {json.dumps(formulation_candidates, ensure_ascii=False)}\n"
            "Return one decision for each supplied candidate."
        )
        try:
            formulation_decisions=[]
            for extra in (
                "",
                "\\nCounterfactual: replace the candidate with another formulation or texture while holding PRODUCT fixed. If that changes how the product is formulated or feels rather than what it tastes like, choose FORMULATION. Choose TASTE only when the candidate itself names the intended flavor."
            ):
                fr=self._chat_json(
                    [{"role":"user","content":formulation_prompt+extra}],
                    system_prompt=formulation_system,
                    response_schema=formulation_schema,
                )
                fa=fr.get("attributes")
                if isinstance(fa,list):
                    formulation_decisions.append({
                        x.get("text"):x.get("axis") for x in fa if isinstance(x,dict)
                        and isinstance(x.get("text"),str)
                        and x.get("axis") in {"taste","formulation"}
                    })
            if len(formulation_decisions)==2:
                fd={k:v for k,v in formulation_decisions[0].items()
                    if formulation_decisions[1].get(k)==v}
                if fd:
                    refined=[]
                    for item in attrs:
                        if not isinstance(item,dict): continue
                        tv=item.get("text")
                        if tv in fd:
                            item=dict(item)
                            item["kind"]="טעם" if fd[tv]=="taste" else "סוג"
                        refined.append(item)
                    attrs=refined
        except Exception:
            pass

        # Narrow audience-vs-application adjudication.  A target/condition of
        # hair, skin, body area, or application is a product-version attribute,
        # not an audience.  Only a phrase identifying WHO receives/uses the
        # product is audience.
        audience_schema={
            "name":"audience_vs_application_adjudication",
            "strict":True,
            "schema":{
                "type":"object",
                "properties":{
                    "attributes":{
                        "type":"array",
                        "items":{
                            "type":"object",
                            "properties":{
                                "text":{"type":"string"},
                                "axis":{"type":"string","enum":["audience","application","other"]},
                            },
                            "required":["text","axis"],
                            "additionalProperties":False,
                        },
                    }
                },
                "required":["attributes"],
                "additionalProperties":False,
            },
        }
        audience_system=(
            "You are a narrow semantic audience-vs-application judge for Baskit. "
            "PRODUCT is fixed. Do not change PRODUCT, spans, or source text.\n\n"
            "AUDIENCE means WHO the product is intended for as a recipient/user "
            "group: women, men, babies, children, animals, etc.\n"
            "APPLICATION means WHERE/ON WHAT/UNDER WHAT CONDITION the product is "
            "used, including hair type, hair condition, skin type/condition, body "
            "area, surface, task, or use context. Application is a product-version "
            "attribute and maps to סוג, not קהל יעד.\n"
            "Do not classify an application target as audience merely because it "
            "uses a relational phrase. Judge the referent of the phrase."
        )
        audience_candidates=[
            item for item in attrs
            if isinstance(item,dict) and item.get("kind") in {"קהל יעד","סוג"}
        ]
        audience_prompt=(
            f"SOURCE: {source}\nFIXED PRODUCT: {core}\n"
            f"ATTRIBUTES TO JUDGE: {json.dumps(audience_candidates, ensure_ascii=False)}\n"
            "For every supplied candidate return audience, application, or other."
        )
        try:
            ar=self._chat_json(
                [{"role":"user","content":audience_prompt}],
                system_prompt=audience_system,
                response_schema=audience_schema,
            )
            aa=ar.get("attributes")
            if isinstance(aa,list):
                ad={x.get("text"):x.get("axis") for x in aa if isinstance(x,dict)
                    and isinstance(x.get("text"),str) and x.get("axis") in {"audience","application"}}
                if ad:
                    refined=[]
                    for item in attrs:
                        if not isinstance(item,dict): continue
                        tv=item.get("text")
                        if tv in ad:
                            item=dict(item)
                            item["kind"]="קהל יעד" if ad[tv]=="audience" else "סוג"
                        refined.append(item)
                    attrs=refined
        except Exception:
            pass

        # Final source-span hygiene: empty/whitespace items are never semantic
        # attributes. This is structural cleanup only; it does not decide meaning.
        clean_attrs = []
        seen = set()
        for item in attrs if isinstance(attrs, list) else []:
            if not isinstance(item, dict):
                continue
            text_value = item.get("text")
            kind_value = item.get("kind")
            if not isinstance(text_value, str) or not text_value.strip():
                continue
            if not isinstance(kind_value, str) or not kind_value.strip():
                continue
            text_value = text_value.strip()
            kind_value = kind_value.strip()
            if text_value not in source:
                continue
            key = (text_value, kind_value)
            if key in seen:
                continue
            seen.add(key)
            clean_attrs.append({"text": text_value, "kind": kind_value})
        attrs = clean_attrs

        return {"attributes": attrs}
    def plan(
        self,
        product_name: str,
        known_brand: str = "",
        known_core: str = "",
    ) -> dict[str, Any]:
        """Make an independent semantic boundary decision before final assembly."""
        boundary_schema = {
            "name": "semantic_boundary_plan",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "brand": {"type": "string"},
                    "product": {"type": "string"},
                    "decisions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "base": {"type": "string"},
                                "effect": {
                                    "type": "string",
                                    "enum": ["core_defining", "core_preserving"]
                                }
                            },
                            "required": ["text", "base", "effect"],
                            "additionalProperties": False,
                        },
                    },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string"},
                            },
                            "required": ["text", "kind"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "brand", "product", "decisions", "attributes"],
                "additionalProperties": False,
            },
        }

        messages = [
            {
                "role": "user",
                "content": (
                    "Determine the independent semantic structure for this title before "
                    "any final segmentation is produced. Return brand, product, and attributes only. "
                    "Do not use a draft or candidate segmentation. "
                    "An independently identified brand is supplied below; preserve it as BRAND if it is an exact source substring. "
                    "Do not reinterpret the supplied brand as PRODUCT.\n\n"
                    f"Independently identified brand: {known_brand}\n"
                    f"Independently adjudicated core product: {known_core}\n"
                    "When the independently adjudicated core product is non-empty, "
                    "use that exact source span as PRODUCT and do not expand PRODUCT "
                    "beyond it. Assign following source words according to their "
                    "semantic attribute roles instead. Do not independently re-expand "
                    "the established core boundary.\n\n"
                    f"Product name: {product_name}"
                ),
            }
        ]
        return self._chat_json(
            messages,
            system_prompt=BOUNDARY_JUDGE_SYSTEM_PROMPT,
            response_schema=boundary_schema,
        )

    def review_plan(
        self,
        product_name: str,
        plan: dict[str, Any],
        known_brand: str = "",
        known_core: str = "",
    ) -> dict[str, Any]:
        """Independently audit the proposed product boundary.

        This is deliberately a second semantic decision: it receives the
        candidate plan rather than a final segmentation and must re-test each
        modifier as WHAT product vs WHICH version/property.
        """
        review_schema = {
            "name": "semantic_boundary_review",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "brand": {"type": "string"},
                    "product": {"type": "string"},
                    "decisions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "base": {"type": "string"},
                                "effect": {
                                    "type": "string",
                                    "enum": ["core_defining", "core_preserving"]
                                }
                            },
                            "required": ["text", "base", "effect"],
                            "additionalProperties": False,
                        },
                    },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "kind": {"type": "string"},
                            },
                            "required": ["text", "kind"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text", "brand", "product", "decisions", "attributes"],
                "additionalProperties": False,
            },
        }
        messages = [
            {
                "role": "user",
                "content": (
                    "Audit the proposed semantic boundary plan independently. "
                    "First determine ownership of every source span: commercial identity, "
                    "product identity, attribute, or structural separator. "
                    "Punctuation/separators are not part of a neighboring semantic span "
                    "unless the source itself makes them semantically meaningful. "
                    "Do not merge adjacent spans solely because they occur next to each other. Before accepting any multi-word PRODUCT, recompute its boundary from scratch. Compare the base-only referent with the full phrase referent. If removing a modifier still leaves the same concrete item and only removes a specification, the modifier must be outside PRODUCT. If removing it changes what concrete item/category the shopper is referring to, the modifier must remain inside PRODUCT. This applies even when the modifier is grammatically an adjective or resembles an attribute kind. Do not use phrase familiarity or catalog wording as evidence.\n"
                    "Do not preserve it merely because it was proposed. Recompute the PRODUCT boundary. "
                    "For every modifier that could be inside PRODUCT or an ATTRIBUTE, perform: "
                    "(1) remove the modifier and judge whether the base is already a concrete useful supermarket category; "
                    "(2) decide WHAT concrete product vs WHICH VERSION/PROPERTY; "
                    "(3) apply the substitution test; "
                    "(4) apply the shopper-search test. "
                    "If the base is already sufficiently informative for the shopper's request, a relational/composition phrase such as a with/in/prepared-with phrase normally remains an ATTRIBUTE. "
                    "Default to the core product. Do not expand PRODUCT just because a modifier makes the title more specific, natural, or catalog-like. "
                    "If removing a modifier leaves a sufficiently informative supermarket product that would not naturally trigger a 'which product/kind?' follow-up, keep the modifier as an ATTRIBUTE. If the base is too vague, keep the modifier in PRODUCT when it is needed to identify the intended product. "
                    "Do not classify a modifier as color/flavor/type before the boundary decision. "
                    "An ATTRIBUTE is a semantic source span, not merely its final noun. "
                    "If a modifier is expressed through a relational, prepositional, "
                    "or compositional phrase, distinguish the semantic carrier from "
                    "the semantic value. Preserve the meaningful value span; omit "
                    "purely relational wording when it adds no independent shopping "
                    "meaning. Do not create a second attribute for such wording.\n"
                    "Return the corrected plan, not an explanation. Preserve exact source substrings.\n\n"
                    f"Original title: {product_name}\n"
                    f"Independently adjudicated core product: {known_core}\n"
                    "If the independently adjudicated core product is non-empty, "
                    "it is the established PRODUCT boundary for this audit. Do not "
                    "expand PRODUCT beyond that exact source span; classify following "
                    "source words as attributes or structural text according to meaning.\n\n"
                    f"Proposed plan to audit: {json.dumps(plan, ensure_ascii=False)}"
                ),
            }
        ]
        return self._chat_json(
            messages,
            system_prompt=BOUNDARY_JUDGE_SYSTEM_PROMPT,
            response_schema=review_schema,
        )

    def fast_parse(self, product_name: str) -> SemanticResult:
        """Single-pass production parser.

        This keeps the full semantic contract and structured JSON schema, but
        removes the repeated brand/core/planner/reviewer/allocation LLM calls.
        The model makes the semantic decision once; Python then performs only
        source-grounded normalization and validation.
        """
        if not isinstance(product_name, str) or not product_name.strip():
            raise ValueError("product_name must be a non-empty string")

        messages = [{
            "role": "user",
            "content": (
                PARSE_INSTRUCTION
                + "\n\nFINAL PRODUCTION PASS: Make the complete semantic decision in this one pass. "
                "Do not ask for or assume a separate planner/reviewer stage. "
                "Return a semantic representation, not a verbatim copy of the title. "
                "Preserve every semantically meaningful source span exactly, but omit "
                "purely grammatical or relational carrier wording when it adds no "
                "independent shopping meaning. When an attribute is expressed as a "
                "relational construction, identify the underlying semantic value first "
                "and emit that value, not the carrier that introduces it. If the carrier "
                "itself has no independent meaning, omit the entire carrier phrase; do "
                "not leave behind a preposition, linker, or generic attribute label as "
                "unclassified or as a second attribute. Never create a second attribute "
                "from the carrier merely because the carrier contains a word that resembles "
                "an ontology kind. This is a semantic decision, not a word list. "
                "Do not truncate the JSON; finish every object and array.ג). "
                "Do not truncate the JSON; finish every object and array.\n\n"
                + f"Product name: {product_name}"
            ),
        }]

        semantic_schema = {
            "name": "semantic_result",
            "strict": True,
            "schema": self._schema_value,
        }
        payload = self._chat_json(
            messages,
            response_schema=semantic_schema,
        )
        return SemanticResult.model_validate(payload)

    def parse(
        self,
        product_name: str,
        semantic_plan: dict[str, Any] | None = None,
    ) -> SemanticResult:
        
        messages: list[dict[str, str]] = []

        plan_text = ""
        if semantic_plan:
            plan_text = (
                "\n\nSEMANTIC BOUNDARY PLAN (established before final segmentation):\n"
                + json.dumps(semantic_plan, ensure_ascii=False)
                + "\nTreat this plan as the semantic boundary decision. Assemble the final source-grounded segments from it; do not collapse a planned ATTRIBUTE into PRODUCT merely because the phrase is natural. "
                "When a planned ATTRIBUTE contains relational wording, do not assume every word belongs in the output. Re-evaluate the words semantically: keep the actual attribute value (including all meaningful words that form that value), and omit purely grammatical/relational carrier wording. Never emit a semantically empty carrier as an unclassified segment merely to reconstruct the title.\n"
            )

        messages.append(
            {
                "role": "user",
                "content": (
                    PARSE_INSTRUCTION
                    + plan_text
                    + f"\n\nProduct name: {product_name}"
                ),
            }
        )

        semantic_schema = {
            "name": "semantic_result",
            "strict": True,
            "schema": self._schema_value,
        }
        payload = self._chat_json(
            messages,
            response_schema=semantic_schema,
        )

        return SemanticResult.model_validate(payload)

    def verify(
        self,
        product_name: str,
        current: SemanticResult,
    ) -> SemanticResult:
        messages: list[dict[str, str]] = ({
            "role": "user",
            "content": (
                f"Product name: {product_name}\n\n"
                "Current output:\n"
                f"{current.model_dump_json(ensure_ascii=False)}\n\n"
                + VERIFY_PROMPT
            ),
        })
        semantic_schema = {
            "name": "semantic_result",
            "strict": True,
            "schema": self._schema_value,
        }
        payload = self._chat_json(
            messages,
            response_schema=semantic_schema,
        )

        return SemanticResult.model_validate(payload)

    def parse_many(
        self,
        product_names: list[str],
    ) -> list[SemanticResult]:
        if not product_names:
            return []

        results: list[SemanticResult] = []

        for name in product_names:
            results.append(self.parse(name))

        return results

    def repair(
        self,
        product_name: str,
        previous: SemanticResult,
        issues: list[str],
        semantic_plan: dict[str, Any] | None = None,
    ) -> SemanticResult:
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
                    + "\n\nSemantic boundary plan:\n"
                    + json.dumps(semantic_plan or {}, ensure_ascii=False)
                    + "\n\n"
                    + "Return only the JSON object. Do not explain.\n\n"
                    + REPAIR_PROMPT
                ),
            },
        ]

        semantic_schema = {
            "name": "semantic_result",
            "strict": True,
            "schema": self._schema_value,
        }
        payload = self._chat_json(
            messages,
            response_schema=semantic_schema,
        )

        return SemanticResult.model_validate(payload)
