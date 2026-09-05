import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SemanticConfig:
    ollama_host: str = os.getenv("BASKIT_OLLAMA_HOST", "http://localhost:8080")
    model: str = os.getenv("BASKIT_MODEL", "qwen3.5:9b")
    temperature: float = float(os.getenv("BASKIT_TEMPERATURE", "0"))
    repair_attempts: int = int(os.getenv("BASKIT_REPAIR_ATTEMPTS", "1"))
    max_examples: int = int(os.getenv("BASKIT_MAX_EXAMPLES", "4"))
    request_timeout: float = float(os.getenv("BASKIT_REQUEST_TIMEOUT", "120"))
    training_examples_path: str = os.getenv(
        "BASKIT_TRAINING_EXAMPLES", str(BASE_DIR / "baskit_training_examples_hebrew_v1.jsonl")
    )
    checks_path: str = os.getenv(
        "BASKIT_CHECKS", str(BASE_DIR / "baskit_semantic_checks_hebrew_v1.jsonl")
    )


CONFIG = SemanticConfig()