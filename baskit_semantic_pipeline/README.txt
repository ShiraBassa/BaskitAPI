BASKIT FAST SEMANTIC PIPELINE

The production path keeps the same Qwen3.5-4B Q4_K_M model and the full semantic
contract, but reduces normal inference to ONE LLM call per product.

Recommended llama.cpp server:

llama-server \
  -hf bartowski/Qwen_Qwen3.5-4B-GGUF:Q4_K_M \
  --no-mmproj \
  --n-gpu-layers 99 \
  --flash-attn on \
  --batch-size 1024 \
  --ubatch-size 256 \
  --parallel 1 \
  --cache-reuse 256 \
  --reasoning off \
  --port 8080

Then:

cd baskit_semantic_pipeline
python benchmark.py

Fast mode is enabled by default:

BASKIT_FAST_MODE=1
BASKIT_MAX_OUTPUT_TOKENS=256

Optional environment variables:

BASKIT_OLLAMA_HOST=http://localhost:8080
BASKIT_MODEL=qwen3.5-4b-q4_k_m
BASKIT_TEMPERATURE=0.01
BASKIT_REPAIR_ATTEMPTS=1
BASKIT_JSON_RETRY_ATTEMPTS=1

LEGACY COMPARISON

Set:

BASKIT_FAST_MODE=0

This restores the original multi-stage semantic pipeline so you can compare
accuracy and latency against the new fast path.

IMPORTANT

The optimization is deliberately pipeline-level rather than model-level:
- Qwen3.5-4B Q4_K_M remains the semantic model.
- The full semantic identity contract remains in the prompt.
- No product dictionaries, hard-coded phrases, or benchmark-specific rules are added.
- Python only performs structural normalization/source validation after the model answer.
- A repair call is used only when deterministic validation fails.
