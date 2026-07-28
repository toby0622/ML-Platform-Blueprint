#!/bin/sh
set -eu

is_boolean() {
  case "$2" in
    true|false) ;;
    *)
      echo "$1 must be either true or false; received '$2'" >&2
      exit 64
      ;;
  esac
}

is_boolean VLLM_ENABLE_PREFIX_CACHING "$VLLM_ENABLE_PREFIX_CACHING"
is_boolean VLLM_ENABLE_CHUNKED_PREFILL "$VLLM_ENABLE_CHUNKED_PREFILL"

set -- serve "$VLLM_MODEL" \
  --served-model-name "$VLLM_SERVED_MODEL_NAME" \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype "$VLLM_DTYPE" \
  --max-model-len "$VLLM_MAX_MODEL_LEN" \
  --gpu-memory-utilization "$VLLM_GPU_MEMORY_UTILIZATION" \
  --max-num-seqs "$VLLM_MAX_NUM_SEQS" \
  --kv-cache-dtype "$VLLM_KV_CACHE_DTYPE"

if [ "$VLLM_ENABLE_PREFIX_CACHING" = "true" ]; then
  set -- "$@" --enable-prefix-caching
else
  set -- "$@" --no-enable-prefix-caching
fi

if [ "$VLLM_ENABLE_CHUNKED_PREFILL" = "true" ]; then
  set -- "$@" --enable-chunked-prefill
else
  set -- "$@" --no-enable-chunked-prefill
fi

if [ -n "$VLLM_MAX_NUM_BATCHED_TOKENS" ]; then
  set -- "$@" --max-num-batched-tokens "$VLLM_MAX_NUM_BATCHED_TOKENS"
fi

if [ -n "$VLLM_QUANTIZATION" ]; then
  set -- "$@" --quantization "$VLLM_QUANTIZATION"
fi

if [ -n "$VLLM_MODEL_REVISION" ]; then
  set -- "$@" --revision "$VLLM_MODEL_REVISION"
fi

# These variables configure this wrapper, not vLLM itself. Remove them before
# exec so vLLM's unknown-environment-variable guard reports only real mistakes.
unset VLLM_MODEL \
  VLLM_MODEL_REVISION \
  VLLM_SERVED_MODEL_NAME \
  VLLM_DTYPE \
  VLLM_QUANTIZATION \
  VLLM_MAX_MODEL_LEN \
  VLLM_GPU_MEMORY_UTILIZATION \
  VLLM_MAX_NUM_SEQS \
  VLLM_MAX_NUM_BATCHED_TOKENS \
  VLLM_ENABLE_PREFIX_CACHING \
  VLLM_ENABLE_CHUNKED_PREFILL \
  VLLM_KV_CACHE_DTYPE

exec vllm "$@"
