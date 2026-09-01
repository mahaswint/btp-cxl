#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/BTP_CXL_Study"
LLAMA="$ROOT/workloads/llama_cpp/llama.cpp/build/bin/llama-cli"
PROMPT_FILE="$ROOT/workloads/llama_cpp/runs/fixed_prompt.txt"

exec "$LLAMA" \
    -hf bartowski/Llama-3.2-1B-Instruct-GGUF:Q4_K_M \
    -f "$PROMPT_FILE" \
    -n 128 \
    -t 8 \
    -tb 8 \
    --single-turn \
    --simple-io \
    --log-disable \
    --no-display-prompt \
    --temp 0
