from __future__ import annotations

from semantic_ai_config import CONFIG, SemanticConfig
from semantic_ai_examples import build_few_shot_messages
from semantic_ai_llm import OllamaSemanticLLM
from semantic_ai_validation import validate_semantics


class SemanticEngine:
    """
    Public Baskit semantic engine.

    The LLM performs semantic interpretation.
    Validation performs structural/safety checks.
    """

    def __init__(self, config: SemanticConfig = CONFIG):
        self.config = config
        self.llm = OllamaSemanticLLM(config)

    def _get_few_shot_examples(self, product_name: str) -> list[dict[str, str]]:
        if self.config.max_examples <= 0:
            return []
        return build_few_shot_messages(
            max_examples=self.config.max_examples,
            target_text=product_name,
            examples_path=self.config.training_examples_path,
        )

    def parse(self, product_name: str) -> dict:
        examples = self._get_few_shot_examples(product_name)
        result = self.llm.parse(product_name, examples=examples)
        issues = validate_semantics(product_name, result)

        for _ in range(self.config.repair_attempts):
            if not issues:
                break
            result = self.llm.repair(product_name, result, issues)
            issues = validate_semantics(product_name, result)

        return {
            "text": product_name,
            "segments": [s.model_dump() for s in result.segments],
            "valid": not issues,
            "validation_errors": issues,
        }

    def parse_many(self, product_names: list[str]) -> list[dict]:
        if not product_names:
            return []

        return [self.parse(product_name) for product_name in product_names]


def parse_product(product_name: str) -> dict:
    return SemanticEngine().parse(product_name)