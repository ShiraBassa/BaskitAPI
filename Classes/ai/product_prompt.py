"""Prompt and schema construction for semantic product parsing."""

from __future__ import annotations

from typing import Any


def semantic_schema() -> dict[str, Any]:
    """Return the structured-output schema used by the semantic parser."""
    return {
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "role": {
                            "type": "string",
                            "enum": [
                                "product",
                                "brand",
                                "attribute",
                                "unclassified",
                            ],
                        },
                        "kind": {
                            "type": "string",
                            "maxLength": 50,
                            "pattern": r"^(?:[\u0590-\u05FF]+(?:[ -][\u0590-\u05FF]+)*)?$",
                            "description": (
                                "A concise semantic attribute label. For Hebrew source products, the value must consist only of natural Hebrew words. Only attribute segments use a non-empty kind; all other segments use an empty string."
                            ),
                        },
                    },
                    "required": ["text", "role", "kind"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["segments"],
        "additionalProperties": False,
    }


def semantic_prompt(product_name: str, run_number: int = 1) -> str:
    """Build the semantic parsing prompt."""
    return f"""You are Baskit's semantic supermarket-product parser.

SOURCE PRODUCT:
{product_name}

Understand this complete supermarket product name and classify every part by its semantic role.

LANGUAGE

Use one language consistently for all natural-language values in the output.
The output language must be the language of the source product.
Every natural-language value must be written naturally and fluently in that language.
The structured output schema enforces the required language format; follow that constraint exactly.
Preserve source-derived values exactly as they appear in the source.
Generate semantic values naturally in the source language.
The role value is a fixed structural classification value from the schema; do not translate it.
The JSON structure keys remain exactly: segments, text, role, kind.

ROLES

product = the fundamental supermarket item the shopper is buying. It answers "What is this item?" and identifies the actual kind of thing being purchased, not who makes or sells it.
brand = the commercial or manufacturer identity attached to that product. It answers "Who makes or sells this product?" and identifies the company, manufacturer, or commercial brand, not what the item itself is.
attribute = a meaningful characteristic, variant, composition, size, quantity, flavor, or other property of the product.
unclassified = wording whose semantic role cannot be determined confidently.

Determine product identity before assigning the other roles. Ask: "What item is the shopper buying?" The answer is the product segment. Then ask: "Which part identifies the commercial or manufacturer identity of that product?" That part is the brand segment.

Do not let the possible existence of a word as a brand override its meaning and role in the complete product phrase.
Do not force a segment into brand, attribute, or another role when its role is not supported by the complete phrase.
A product identity and a brand identity are different semantic concepts. A product is what the item is; a brand is the commercial identity under which that item is sold. A manufacturer or company name should be considered brand information when it identifies the commercial source of the product, not an attribute of the product. Do not classify a commercial/manufacturer identity as an attribute such as type, flavor, size, or another characteristic.

When the phrase contains both an item identity and a commercial/manufacturer identity, keep them as two separate semantic roles: the item identity is product and the commercial/manufacturer identity is brand.
A brand describes who makes, owns, or commercially identifies the product; it does not describe what the product is.
An attribute describes a property of the product; it must not be used as a substitute for either product identity or brand identity.
Do not invent an attribute interpretation merely to assign a role to a segment.
If both product and brand can be identified from the complete phrase, preserve both roles independently.

SEMANTIC METADATA

Only attribute segments have semantic metadata in `kind`.
For product, brand, and unclassified segments, `kind` must be an empty string.

For attribute segments, use a consistent set of general, natural supermarket attribute names whenever they fit the meaning of the source value.
Prefer these established attribute names:
- אחוז שומן
- כמות
- משקל
- טעם
- סוג
- גודל
- צבע
- מרקם
- צורה
- אריזה
- מספר יחידות
- אחוז

These are preferred general category names, not mandatory mappings. Choose one when it accurately represents the source value and fits the product context.
Use כמות as the category for quantity and volume information. Use משקל as the category for weight information. Prefer these category names consistently whenever they fit the meaning of the source value.
If none of the preferred names accurately describes the attribute, create a new short, natural, commonly understood Hebrew attribute name that accurately represents the property.
Never force an attribute into a preferred category when that category does not fit its meaning.

`kind` names the characteristic, while `text` contains the value of that characteristic.
Determine the characteristic from the complete product context, not from the value alone.
Use the most natural and consistent category name possible.

IDENTITY

First determine the fundamental product represented by the complete source phrase.
Then determine whether another segment represents the commercial or manufacturer identity of that product.
Then identify meaningful product characteristics as attributes and give each one a concise, conventional semantic kind in the source product language.
The product and brand decisions must be based on the meaning of the complete phrase, not on whether an individual word could independently be interpreted as a brand.

OUTPUT QUALITY

Before returning JSON, perform one final language-consistency check over every natural-language value.
Every natural-language value must use the source product language consistently and must satisfy the structured output schema.
Every product, brand, and unclassified segment must have an empty `kind`.
Every attribute segment must have a concise, conventional semantic `kind` that a native-speaking supermarket shopper would commonly use for that characteristic.

The required JSON field names and fixed role values are structural schema values and must remain exactly as specified.

SOURCE TEXT

Every text field must be copied directly from the source product.
Keep the original wording, language, characters, and order.
Together, the segment text fields must cover the complete source phrase exactly once.

Return JSON only:

{{
  "segments": [
    {{"text": "...", "role": "product", "kind": ""}},
    {{"text": "...", "role": "brand", "kind": ""}},
    {{"text": "...", "role": "attribute", "kind": "..."}},
    {{"text": "...", "role": "unclassified", "kind": ""}}
  ]
}}
"""
