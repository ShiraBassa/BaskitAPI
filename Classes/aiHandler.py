from datetime import datetime
from pathlib import Path
import json
import re
import threading
import time
import urllib.error
import urllib.request

from Data.data_sets import items_info_ref
from Classes.ai.category_classifier import CategoryClassifier
from Classes.ai.classification_cache import ClassificationCache

from Classes.ai.product_normalizer import ProductNormalizer
from Classes.ai.ollama_client import OllamaClient


OLLAMA_URL = "http://localhost:11434/api/generate"

ATTRIBUTE_MAX_RETRIES = 1


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_TRAINING_DB = PROJECT_ROOT / "Data" / "baskit_ai_training.db"
NORMALIZATION_TABLE = "normalization_labels"


def log(message, level="INFO"):
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] "
        f"[{level}] {message}"
    )


def _call_local_ai(products, ollama_client=None):
    if not products:
        return []

    normalized_products = [
        (str(code), str(name).strip())
        for code, name in products
        if name is not None and str(name).strip()
    ]

    if not normalized_products:
        return []

    normalizer = ProductNormalizer(
        ollama_client or OllamaClient()
    )
    results = []

    for code, product_name in normalized_products:
        fields = None

        for attempt in range(1, ATTRIBUTE_MAX_RETRIES + 2):
            try:
                fields = normalizer.normalize(product_name)
                break
            except (ValueError, TimeoutError, OSError) as exc:
                log(
                    f"Name-normalizer failed for {product_name!r} "
                    f"attempt {attempt}/{ATTRIBUTE_MAX_RETRIES + 1}: {exc}",
                    "WARNING",
                )

        if fields is None:
            log(
                f"Name-normalizer failed for {product_name!r}; "
                "keeping original name.",
                "WARNING",
            )
            search_name = product_name
            brand = ""
        else:
            brand = fields.brand.strip()
            search_name = normalizer.remove_brand(product_name, brand)

        results.append({
            "item_code": code,
            "search_name": search_name,
            "brand": brand,
        })

    log(
        "Name-normalizer complete: "
        f"{len(results)}/{len(normalized_products)} products processed."
    )

    return results


class AIHandler:

    def __init__(
        self,
        item_codes,
    ):

        self.item_codes = item_codes
        self.is_running = False

        self.ollama_client = OllamaClient()

        self.cache = (
            ClassificationCache()
        )
        self.product_normalizer = ProductNormalizer(
            self.ollama_client
        )

        self.category_classifier = (
            CategoryClassifier(
                client=self.ollama_client
            )
        )

    def set_items(
        self,
        item_codes,
    ):

        self.item_codes = item_codes

    def classify_products(
        self,
        products,
    ):

        return _call_local_ai(
            products,
            self.ollama_client
        )

    def run_async(self):

        if self.is_running:
            return

        self.is_running = True

        def run():

            try:
                self.classify_items()

            except Exception as exc:

                log(
                    "AI background classification "
                    f"failed: {exc}",
                    "ERROR",
                )

            finally:

                self.is_running = False

        threading.Thread(
            target=run,
            daemon=True,
        ).start()

    def classify_items(
        self,
        chunk_size=100,
        min_interval=0,
    ):

        if not self.item_codes:
            return {}

        existing = (
            self.cache
            .load_product_classifications()
        )

        requested = [
            str(code)
            for code in self.item_codes
            if code
        ]

        missing = [
            code
            for code in requested
            if code not in existing
        ]

        if not missing:

            return {
                code: existing[code]
                for code in requested
                if code in existing
            }

        try:

            info = (
                items_info_ref.get()
                or {}
            )

        except Exception as exc:

            log(
                "Failed loading item information: "
                f"{exc}",
                "ERROR",
            )

            return {}

        results = {
            code: existing[code]
            for code in requested
            if code in existing
        }

        for start in range(
            0,
            len(missing),
            chunk_size,
        ):

            codes = missing[
                start:
                start + chunk_size
            ]

            items = []

            for code in codes:

                item = info.get(
                    code
                )

                if (
                    isinstance(item, dict)
                    and isinstance(
                        item.get("name"),
                        str,
                    )
                    and item["name"].strip()
                ):

                    items.append(
                        (
                            code,
                            item["name"].strip(),
                        )
                    )

            if not items:
                continue

            log(
                f"Normalizing {len(items)} product names with local AI..."
            )

            normalized = _call_local_ai(
                items,
                self.ollama_client
            )

            if not normalized:
                continue

            search_items = [
                (result["item_code"], result["search_name"])
                for result in normalized
            ]

            # Grouping is intentionally exact: identical search names are the same group.
            # No AI or semantic similarity is used here.
            groups = {
                str(item_code): search_name
                for item_code, search_name in search_items
                if search_name
            }

            log(
                f"Exact-name grouping complete: "
                f"{len(groups)} products -> "
                f"{len(set(groups.values()))} unique groups."
            )

            if not groups:
                continue

            unique = list(
                dict.fromkeys(
                    groups.values()
                )
            )

            cached = (
                self.cache
                .load_group_categories()
            )

            reusable = {
                group: cached[group]
                for group in unique
                if cached.get(group)
            }

            log(
                f"Category cache: reused "
                f"{len(reusable)}/"
                f"{len(unique)} groups; "
                f"AI needed for "
                f"{len(unique) - len(reusable)} "
                "groups."
            )

            try:

                categories = (
                    self.category_classifier
                    .classify(
                        unique,
                        reusable,
                    )
                )

            except Exception as exc:

                log(
                    "Local AI category "
                    "classification failed: "
                    f"{exc}",
                    "ERROR",
                )

                continue

            updates = {}

            for code, group in groups.items():

                if categories.get(
                    group
                ):

                    updates[code] = {
                        "category": (
                            categories[group]
                        ),
                        "general_group": group,
                    }

            if updates:

                self.cache.save(
                    updates
                )

                results.update(
                    updates
                )

                log(
                    f"Saved {len(updates)} "
                    "local AI classifications."
                )

            if min_interval > 0:
                time.sleep(
                    min_interval
                )

        log(
            "Local AI classification complete: "
            f"{len(results)}/"
            f"{len(requested)} "
            "products classified."
        )

        return results