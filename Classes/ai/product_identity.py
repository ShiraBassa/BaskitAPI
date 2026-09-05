"""Semantic product identity resolution for Baskit.

Architecture:
    RAW PRODUCT
        ↓
    AI semantic analysis
        ↓
    strict grounding validation
        ↓
    deterministic display-name construction
        ↓
    deterministic exact grouping

The AI is responsible for understanding semantics.
Python is responsible for safety, grounding, text manipulation, and grouping.

There are intentionally NO hard-coded:
    - brands
    - companies
    - manufacturers
    - product names
    - product-specific rules
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .ollama_client import OllamaClient


@dataclass
class RawProduct:
    item_code: str
    raw_name: str
    manufacturer: str = ""
    manufacturer_description: str = ""
    category: str = ""
    quantity: str = ""
    unit: str = ""


@dataclass
class CanonicalProduct:
    raw_name: str
    product: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    brand: str = ""
    manufacturer: str = ""
    quantity: str = ""
    unit: str = ""
    display_name: str = ""
    status: str = "needs_review"


class ProductIdentityResolver:
    """
    Resolve retail product identity using AI semantic segmentation plus strict
    deterministic validation.

    The AI decides what each source span means.
    Python guarantees that the answer is grounded, non-overlapping, and safe.

    There are intentionally NO hard-coded brands, companies, manufacturers,
    products, or product-specific rules.
    """

    SYSTEM = """אתה מנוע סמנטי לזיהוי זהות מוצרי סופרמרקט.

נתח את RAW_NAME כמחרוזת שלמה וחלק אותו לקטעי טקסט סמנטיים.

לכל קטע החזר:
- text: טקסט רציף שמופיע בדיוק ב-RAW_NAME
- role: אחד בלבד מתוך product, attribute, brand, manufacturer, quantity, unit, noise

המטרה המרכזית: להפריד בין זהות המוצר לבין מידע מסחרי, כמותי, אריזתי או שיווקי שאינו חלק מהזהות.
אל תתייחס לכל מילה כ-product כברירת מחדל. קבע את התפקיד של כל חלק לפי המשמעות של שם המוצר כמכלול.

הגדרות:
- product = ליבת המוצר וכל המילים הנדרשות כדי להבין מה קונים.
- attribute = מאפיין מהותי שמבדיל בין וריאציות של אותו מוצר, כגון טעם, סוג, וריאציה, אחוז, חומר או תכונה משמעותית.
- brand = שם מסחרי של המוצר או סדרת המוצרים. הוא יכול להיות שונה מהיצרן.
- manufacturer = היצרן, כאשר ניתן לזהותו בביטחון מתוך RAW_NAME או מידע המקור.
- quantity = מספר או ביטוי המציין כמות.
- unit = יחידת הכמות.
- noise = מידע שאינו חלק מזהות המוצר ואינו משנה את כוונת הקנייה, כגון מידע אריזתי, מבצעי או שיווקי.

כללי החלטה:
1. נתח את כל RAW_NAME לפני חלוקת הקטעים.
2. אל תשתמש ברשימות קשיחות של מותגים, חברות, יצרנים או מוצרים.
3. אל תשתמש בכללים שנכתבו עבור מוצר מסוים.
4. אל תנחש זהות מסחרית. עם זאת, כאשר ההקשר של שם המוצר מספק ראיה מספקת לכך שרצף מילים הוא brand, סווג אותו כ-brand במקום להשאיר אותו כ-product רק מתוך זהירות.
5. brand ו-manufacturer הם ישויות מסחריות שונות. אל תניח שהם אותו דבר.
6. מילה שנראית כמו שם אינה brand אוטומטית. החלט לפי תפקידה בתוך שם המוצר.
7. ביטוי מסחרי רב-מילתי חייב להיות קטע brand אחד שלם כאשר הוא מזוהה כיחידה מסחרית.
8. product חייב לכלול את כל המילים הדרושות להבנת מהו המוצר. אל תעביר מילה חיונית ל-attribute רק כדי לקצר product.
9. attribute משמש רק כאשר הערך באמת משנה את המוצר או את וריאציית הקנייה. אחוז, טעם, סוג וכדומה הם attribute כאשר הם וריאציה מהותית; הם אינם noise רק משום שהם קצרים.
10. מידע כמותי הוא quantity/unit רק כאשר הוא מופיע ב-RAW_NAME או במידע המקור.
11. אם MANUFACTURER מסופק והוא תואם או מסביר זהות יצרן, מותר להשתמש בו כ-manufacturer גם אם אינו מופיע ב-RAW_NAME.
12. אין לנרמל, לתרגם, לתקן איות, לשכתב או להמציא text. כל text חייב להיות רצף מדויק מתוך RAW_NAME, למעט manufacturer/quantity/unit שמגיעים במפורש משדות המקור המותרים.
13. הקטעים אינם חייבים להיות כל המחרוזת, אבל כל מידע משמעותי צריך לקבל תפקיד. אין להשאיר חלק משמעותי ללא סיווג רק כדי להיות שמרני.
14. אל תסווג את כל RAW_NAME כ-product כאשר ניתן להפריד ממנו בביטחון brand, manufacturer, quantity, unit או noise.
15. אם אין brand ברור, השאר brand ריק. אם אין manufacturer ברור, השאר manufacturer ריק.
16. אם אין מאפיין מהותי, השאר attribute מחוץ לרשימה.
17. אין להחזיר placeholders כגון "לא צוין", "unknown", "none" או טקסט הסבר.
18. אין להחזיר שמות שדות, כותרות prompt או הוראות כ-text של קטע.
19. אל תחלק מילה אחת לכמה קטעים.
20. product חייב להיות לפחות קטע אחד עבור מוצר תקין.

חשוב במיוחד:
- שאל את עצמך עבור כל רצף מילים: האם הוא מתאר מה המוצר, וריאציה של המוצר, זהות מסחרית, יצרן, כמות/יחידה, או רעש?
- אין להעדיף product רק מפני שזה הפתרון הבטוח ביותר. העדף את הסיווג הסמנטי הנכון.
- display_name אינו מוחזר על ידי המודל. Python יבנה אותו רק מהקטעים שסווגו.

החזר JSON בלבד לפי הסכמה שסופקה.
"""

    VALID_ROLES = {
        "product",
        "attribute",
        "brand",
        "manufacturer",
        "quantity",
        "unit",
        "noise",
    }

    def __init__(self, ollama_client: OllamaClient | None = None):
        self.ollama_client = ollama_client or OllamaClient()

    def build_prompt(self, item: RawProduct) -> str:
        return (
            "נתח את פריט הסופרמרקט הבא כמכלול באמצעות קטעים סמנטיים לא-חופפים.\n\n"
            "המטרה היא לזהות מה חייב להישאר בשם המוצר ומה ניתן להסיר בלי לשנות את זהות המוצר.\n"
            "אל תתייחס לכל הטקסט כ-product כברירת מחדל. בצע סיווג סמנטי אמיתי של כל חלק.\n\n"
            "החזר JSON בלבד לפי הסכמה.\n"
            "כל text חייב להיות רצף מדויק מתוך RAW_NAME, למעט מידע manufacturer/quantity/unit שמגיע במפורש משדות המקור המותרים.\n"
            "אל תכניס לשדה text שמות שדות, כותרות, הוראות, או טקסט מתוך ה-prompt.\n"
            "אל תיצור שם חדש, אל תתרגם, אל תנרמל ואל תנחש.\n\n"
            "עבור כל חלק משמעותי של RAW_NAME קבע אם הוא product, attribute, brand, manufacturer, quantity, unit או noise.\n"
            "brand הוא זהות מסחרית ויכול להיות שונה מהיצרן.\n"
            "אם יש רצף מילים שהוא זהות מסחרית אחת, החזר את כל הרצף כ-brand אחד.\n"
            "אם מילה חיונית להבנת המוצר, השאר אותה בתוך product.\n"
            "אם אחוז, טעם, סוג או וריאציה משנים את המוצר, סווג אותם כ-attribute.\n"
            "אל תשתמש ב-attribute רק כדי לקצר product.\n"
            "כמות ויחידה צריכים להיות מסווגים בנפרד כאשר הם מופיעים בשם.\n"
            "השתמש ב-noise רק למידע שבאמת אינו משנה את זהות המוצר.\n"
            "אם אין brand ברור, brand צריך להיות ריק. אם אין manufacturer ברור, manufacturer צריך להיות ריק.\n"
            "אין להחזיר placeholders כגון לא צוין, unknown או none.\n"
            "אין להחזיר טקסט שאינו שייך ל-RAW_NAME כ-segment text.\n\n"
            "IMPORTANT: The only valid raw segment text comes from the value after RAW_NAME below.\n"
            "Never copy MANUFACTURER, SOURCE_CATEGORY, SOURCE_QUANTITY, SOURCE_UNIT, ITEM_CODE,\n"
            "or any prompt label into a segment.\n\n"
            "RETURN JSON ONLY.\n\n"
            f"ITEM_CODE: {item.item_code}\n"
            f"RAW_NAME: {item.raw_name}\n"
            f"MANUFACTURER: {item.manufacturer}\n"
            f"MANUFACTURER_DESCRIPTION: {item.manufacturer_description}\n"
            f"SOURCE_CATEGORY: {item.category}\n"
            f"SOURCE_QUANTITY: {item.quantity}\n"
            f"SOURCE_UNIT: {item.unit}\n"
        )

    @staticmethod
    def schema() -> dict[str, Any]:
        return {
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
                                    "product",
                                    "attribute",
                                    "brand",
                                    "manufacturer",
                                    "quantity",
                                    "unit",
                                    "noise",
                                ],
                            },
                        },
                        "required": ["text", "role"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["segments"],
            "additionalProperties": False,
        }

    @staticmethod
    def _string(value: Any, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError(
                f"Identity field '{field_name}' must be a string"
            )
        return value.strip()

    @classmethod
    def _parse_segments(cls, data: dict[str, Any]) -> list[dict[str, str]]:
        segments = data.get("segments")
        if not isinstance(segments, list):
            raise ValueError("Identity response 'segments' must be an array")

        parsed: list[dict[str, str]] = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                raise ValueError(f"Segment {index} must be an object")

            text = cls._string(segment.get("text", ""), f"segments[{index}].text")
            role = cls._string(segment.get("role", ""), f"segments[{index}].role").casefold()

            if not text:
                raise ValueError(f"Segment {index} has empty text")
            if role not in cls.VALID_ROLES:
                raise ValueError(f"Invalid segment role: {role!r}")

            parsed.append({"text": text, "role": role})

        return parsed

    @staticmethod
    def _find_non_overlapping_spans(
        source: str,
        segments: list[dict[str, str]],
    ) -> list[tuple[int, int, dict[str, str]]]:
        """Locate returned segments in RAW_NAME without allowing overlap.

        Matching is whitespace-tolerant because the model may return a source
        span such as ``3%`` while the raw feed contains equivalent spacing.
        The actual display text is never taken from the model: Python always
        uses the exact source slice.
        """
        source_folded = source.casefold()
        found: list[tuple[int, int, dict[str, str]]] = []
        occupied: list[tuple[int, int]] = []

        def locate(text: str, start_at: int = 0) -> tuple[int, int] | None:
            text_folded = text.casefold().strip()
            if not text_folded:
                return None

            # First try exact substring matching.
            index = source_folded.find(text_folded, start_at)
            while index >= 0:
                end = index + len(text_folded)
                if not any(
                    index < occupied_end and end > occupied_start
                    for occupied_start, occupied_end in occupied
                ):
                    return index, end
                index = source_folded.find(text_folded, index + 1)

            # Then allow arbitrary whitespace runs to match a single space.
            # This handles harmless formatting differences without allowing
            # invented characters or reordered words.
            parts = re.split(r"\s+", text_folded)
            if not parts:
                return None

            pattern = r"\s+".join(re.escape(part) for part in parts if part)
            if not pattern:
                return None

            for match in re.finditer(pattern, source_folded[start_at:]):
                index = start_at + match.start()
                end = start_at + match.end()
                if not any(
                    index < occupied_end and end > occupied_start
                    for occupied_start, occupied_end in occupied
                ):
                    return index, end

            return None

        for segment in segments:
            text = segment["text"]
            chosen = locate(text)

            if chosen is None:
                raise ValueError(
                    "Segment text is not present in raw_name as a "
                    f"non-overlapping span: {text!r}"
                )

            start, end = chosen
            found.append((start, end, segment))
            occupied.append((start, end))

        found.sort(key=lambda value: (value[0], value[1]))

        previous_end = -1
        for start, end, segment in found:
            if start < previous_end:
                raise ValueError(
                    "Semantic segments overlap: "
                    f"{segment['text']!r}"
                )
            previous_end = end

        return found

    @staticmethod
    def _covered_text(source: str, spans: list[tuple[int, int, dict[str, str]]]) -> str:
        return " ".join(source[start:end] for start, end, _ in spans)

    @classmethod
    def _build_fields(
        cls,
        item: RawProduct,
        segments: list[dict[str, str]],
        spans: list[tuple[int, int, dict[str, str]]],
    ) -> dict[str, Any]:
        by_role: dict[str, list[str]] = {role: [] for role in cls.VALID_ROLES}

        for _, _, segment in sorted(spans, key=lambda value: value[0]):
            by_role[segment["role"]].append(segment["text"])

        product_parts = by_role["product"]
        attribute_parts = by_role["attribute"]
        brand_parts = by_role["brand"]
        manufacturer_parts = by_role["manufacturer"]
        quantity_parts = by_role["quantity"]
        unit_parts = by_role["unit"]

        if not product_parts:
            raise ValueError("AI must identify at least one product segment")

        # Reconstruct fields from the exact source slices, in source order.
        # Never concatenate model-generated wording into user-visible fields.
        ordered_segments = sorted(spans, key=lambda value: value[0])

        def source_role_text(role: str) -> str:
            return " ".join(
                item.raw_name[start:end]
                for start, end, segment in ordered_segments
                if segment["role"] == role
            ).strip()

        product = source_role_text("product")
        brand = source_role_text("brand")
        manufacturer = source_role_text("manufacturer")
        quantity = source_role_text("quantity")
        unit = source_role_text("unit")

        attributes: dict[str, str] = {}
        for index, value in enumerate(attribute_parts, start=1):
            # Keep the model's semantic value, but use the exact source slice
            # for the value so validation and display remain grounded.
            source_value = source_role_text("attribute")
            attribute_values = [
                item.raw_name[start:end]
                for start, end, segment in ordered_segments
                if segment["role"] == "attribute"
            ]
            if index <= len(attribute_values):
                source_value = attribute_values[index - 1].strip()
            attributes[f"attribute_{index}"] = source_value

        return {
            "product": product,
            "attributes": attributes,
            "brand": brand,
            "manufacturer": manufacturer,
            "quantity": quantity,
            "unit": unit,
        }

    @classmethod
    def validate(
        cls,
        item: RawProduct,
        segments: list[dict[str, str]],
    ) -> tuple[dict[str, Any], list[tuple[int, int, dict[str, str]]]]:
        source = item.raw_name.strip()
        if not source:
            raise ValueError("Raw product name is empty")

        spans = cls._find_non_overlapping_spans(source, segments)
        # The source slice is authoritative. This prevents harmless model
        # whitespace differences from becoming invented display text.
        for start, end, segment in spans:
            if not source[start:end].strip():
                raise ValueError("Semantic segment resolves to empty source text")
        fields = cls._build_fields(item, segments, spans)

        # A segment labelled manufacturer is allowed to come from source text
        # or from explicitly supplied manufacturer metadata.
        supplied_manufacturer = item.manufacturer.strip()
        supplied_description = item.manufacturer_description.strip()
        for segment in segments:
            if segment["role"] != "manufacturer":
                continue
            text = segment["text"]
            if text.casefold() in source.casefold():
                continue
            if supplied_manufacturer and text.casefold() == supplied_manufacturer.casefold():
                continue
            if supplied_description and text.casefold() == supplied_description.casefold():
                continue
            raise ValueError(
                f"Manufacturer segment is not grounded in source metadata: {text!r}"
            )

        # Quantity/unit may be supplied by structured source metadata.
        for role, metadata in (
            ("quantity", item.quantity.strip()),
            ("unit", item.unit.strip()),
        ):
            for segment in segments:
                if segment["role"] != role:
                    continue
                text = segment["text"]
                if text.casefold() in source.casefold():
                    continue
                if metadata and text.casefold() == metadata.casefold():
                    continue
                raise ValueError(
                    f"{role} segment is not grounded in raw_name or source metadata: {text!r}"
                )

        # Brand/manufacturer cannot be the entire raw product.
        if fields["brand"] and fields["brand"].casefold() == source.casefold():
            raise ValueError("brand cannot equal the entire raw product name")
        if fields["manufacturer"] and fields["manufacturer"].casefold() == source.casefold():
            raise ValueError("manufacturer cannot equal the entire raw product name")

        return fields, spans

    @classmethod
    def _build_display_name(
        cls,
        item: RawProduct,
        spans: list[tuple[int, int, dict[str, str]]],
    ) -> str:
        """
        Build the public name deterministically from AI-labelled source spans.

        Only text explicitly labelled brand/manufacturer/quantity/unit/noise is
        removed. Product and attribute spans remain exactly as written in the
        raw source. Any unlabelled source text is preserved, so an AI omission
        can never silently delete product information.
        """
        source = item.raw_name.strip()

        removable_roles = {
            "brand",
            "manufacturer",
            "quantity",
            "unit",
            "noise",
        }

        removable = [
            (start, end)
            for start, end, segment in spans
            if segment["role"] in removable_roles
        ]

        if not removable:
            return source

        pieces: list[str] = []
        cursor = 0

        for start, end in removable:
            pieces.append(source[cursor:start])
            cursor = end

        pieces.append(source[cursor:])

        result = "".join(pieces)
        result = re.sub(r"\s+", " ", result).strip()
        result = re.sub(r"\s+([,;:])", r"\1", result)
        result = re.sub(r"([([{])\s+", r"\1", result)
        result = re.sub(r"\s+([)\]}])", r"\1", result)
        result = result.strip(" ,;:-")

        # Never allow the semantic pass to accidentally produce an empty
        # public name. The raw source is always the safe fallback.
        return result or source

    @classmethod
    def _construct_verified_product(
        cls,
        item: RawProduct,
        fields: dict[str, Any],
        spans: list[tuple[int, int, dict[str, str]]],
    ) -> CanonicalProduct:
        display_name = cls._build_display_name(item, spans)

        return CanonicalProduct(
            raw_name=item.raw_name.strip(),
            product=fields["product"],
            attributes=fields["attributes"],
            brand=fields["brand"],
            manufacturer=fields["manufacturer"] or item.manufacturer.strip(),
            quantity=fields["quantity"] or item.quantity.strip(),
            unit=fields["unit"] or item.unit.strip(),
            display_name=display_name,
            status="verified",
        )

    def resolve(self, item: RawProduct) -> CanonicalProduct:
        if not isinstance(item, RawProduct):
            raise TypeError("item must be a RawProduct")
        if not item.raw_name.strip():
            raise ValueError("Raw product name must be a non-empty string")

        schema = self.schema()
        last_error: Exception | None = None

        for attempt in range(2):
            if attempt == 0:
                system = self.SYSTEM
                user = self.build_prompt(item)
            else:
                system = (
                    self.SYSTEM
                    + "\n\nVALIDATION RETRY.\n"
                    "Your previous semantic segmentation was rejected. "
                    "Re-analyze RAW_NAME from the beginning and return only valid non-overlapping source spans. "
                    "Do not copy prompt labels or metadata labels into segment text. "
                    "Do not invent wording. "
                    "Do not default the entire name to product merely because a brand is uncertain. "
                    "Preserve all necessary product words, but remove only spans you can semantically classify as brand, manufacturer, quantity, unit, or noise. "
                    "Keep meaningful variants such as type, flavor, percentage, or other purchase-defining attributes. "
                    "For a multi-word commercial identity, return the complete contiguous commercial span."
                )
                user = (
                    self.build_prompt(item)
                    + "\n\nThe previous answer failed deterministic validation. "
                    "Re-evaluate the complete RAW_NAME semantically. "
                    "Return only literal, non-overlapping source spans. "
                    "Do not copy anything from prompt labels into segment text. "
                    "Do not guess, but also do not keep commercial or removable text as product merely out of caution when its semantic role is clear."
                )

            try:
                payload = self.ollama_client.payload(
                    system=system,
                    user=user,
                    schema=schema,
                    num_predict=260,
                )

                response, _ = self.ollama_client.chat(payload)

                if isinstance(response, dict):
                    data = response
                elif isinstance(response, str):
                    data = json.loads(response)
                else:
                    raise ValueError(
                        "Identity response has unsupported type: "
                        f"{type(response).__name__}"
                    )

                if not isinstance(data, dict):
                    raise ValueError("Identity response must be a JSON object")

                segments = self._parse_segments(data)
                fields, spans = self.validate(item, segments)

                return self._construct_verified_product(
                    item,
                    fields,
                    spans,
                )

            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    print(
                        f"[WARNING] Product identity validation failed for "
                        f"{item.raw_name!r}; retrying conservatively: "
                        f"{type(exc).__name__}: {exc}"
                    )
                else:
                    print(
                        f"[WARNING] Product identity resolution failed for "
                        f"{item.raw_name!r}: {type(exc).__name__}: {exc}"
                    )

        return CanonicalProduct(
            raw_name=item.raw_name.strip(),
            manufacturer=item.manufacturer.strip(),
            quantity=item.quantity.strip(),
            unit=item.unit.strip(),
            display_name=item.raw_name.strip(),
            status="needs_review",
        )

    @staticmethod
    def group_key(product: CanonicalProduct) -> str:
        """Exact deterministic grouping by final display name."""
        return product.display_name.strip().casefold()