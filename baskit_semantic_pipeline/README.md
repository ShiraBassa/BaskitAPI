# Baskit Semantic Pipeline

Production-oriented semantic parsing pipeline for Israeli supermarket product names.

## Design

Input Hebrew product text
-> Qwen3.5 via Ollama
-> schema-constrained JSON
-> semantic validation
-> automatic one-shot repair if validation fails
-> stable Baskit result

The model is responsible for semantic interpretation.
Python is responsible for structure, safety, exact-source preservation, and validation.

No brand lists, phrase lists, product-specific rules, or manually encoded semantic mappings are used.

## Requirements

- Python 3.10+
- Ollama
- Qwen3.5 9B

Install:

    pip install -r requirements.txt

Pull the model:

    ollama pull qwen3.5:9b

Run:

    python main.py "דאב - דאודורנט רול און לאישה מלפפון 50 מ\"ל * שלישייה"

The first model download can be several GB. Ollama currently exposes a Qwen3.5 9B package around 6.6 GB in its Q4_K_M distribution.

## Important

The pipeline intentionally does NOT claim semantic correctness merely because JSON is valid.
Validation checks:

- valid JSON / Pydantic schema
- allowed roles
- attribute-kind consistency
- exactly one core product
- exact source text preservation
- no overlapping/duplicated source spans
- no empty semantic text
- no hallucinated text outside the input

If validation fails, the model receives the validation errors and gets one repair attempt.

## Gold / training data

If `train.jsonl` exists, `build_training_data.py` can normalize the existing JSONL into a clean conversational SFT dataset.

The gold labels remain the source of truth. The training pipeline does not invent labels.

## Fine-tuning

Fine-tuning is deliberately a second phase. First benchmark the base model. If systematic semantic errors remain, use:

    python train_lora.py --train train.jsonl --output outputs/baskit-qwen-lora

This uses Hugging Face TRL + PEFT/LoRA.

For Apple Silicon, the recommended local inference path is Ollama. Training can later be moved to an appropriate GPU machine if the dataset/model size requires it.

## Files

- `main.py` - CLI
- `semantic_ai.py` - public semantic engine API
- `semantic_ai_llm.py` - Ollama client
- `semantic_ai_schema.py` - Pydantic output contract
- `semantic_ai_prompts.py` - semantic instructions
- `semantic_ai_validation.py` - structural and semantic-output safety checks
- `semantic_ai_config.py` - environment/configuration
- `build_training_data.py` - convert gold JSONL to SFT format
- `train_lora.py` - optional LoRA fine-tuning
- `benchmark.py` - benchmark runner
- `requirements.txt` - dependencies

## Environment

Optional:

    export BASKIT_OLLAMA_HOST=http://localhost:11434
    export BASKIT_MODEL=qwen3.5:9b
    export BASKIT_TEMPERATURE=0
    export BASKIT_REPAIR_ATTEMPTS=1
    export BASKIT_MAX_EXAMPLES=8

