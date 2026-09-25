import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SemanticConfig:
    ollama_host: str = os.getenv("BASKIT_OLLAMA_HOST", "http://localhost:8080")
    model: str = os.getenv("BASKIT_MODEL", "qwen3.5-4b-q4_k_m")
    temperature: float = float(os.getenv("BASKIT_TEMPERATURE", "0.01"))
    repair_attempts: int = int(os.getenv("BASKIT_REPAIR_ATTEMPTS", "1"))
    request_timeout: float = float(os.getenv("BASKIT_REQUEST_TIMEOUT", "120"))
    max_output_tokens: int = int(os.getenv("BASKIT_MAX_OUTPUT_TOKENS", "512"))
    fast_mode: bool = os.getenv("BASKIT_FAST_MODE", "1").lower() not in {"0", "false", "no", "off"}
    json_retry_attempts: int = int(os.getenv("BASKIT_JSON_RETRY_ATTEMPTS", "1"))
    training_examples_path: str = os.getenv(
        "BASKIT_TRAINING_EXAMPLES", str(BASE_DIR / "baskit_training_examples_hebrew_v2.jsonl")
    )
    checks_path: str = os.getenv(
        "BASKIT_CHECKS", str(BASE_DIR / "baskit_semantic_checks_hebrew_v2.jsonl")
    )


CONFIG = SemanticConfig()