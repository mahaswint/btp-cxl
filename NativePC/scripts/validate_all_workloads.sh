#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/raw_data/validation_all.log"

echo "BTP native workload validation" | tee "$LOG"
echo "Started: $(date)" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

run_test() {
    NAME="$1"
    AFFINITY="$2"
    shift 2

    echo "" | tee -a "$LOG"
    echo "===== TESTING: $NAME =====" | tee -a "$LOG"
    echo "Started: $(date)" | tee -a "$LOG"

    if timeout 20m "$ROOT/scripts/run_native_profile.sh" \
        "$NAME" "$AFFINITY" "$@" >> "$LOG" 2>&1
    then
        echo "RESULT: PASS" | tee -a "$LOG"
    else
        echo "RESULT: FAIL" | tee -a "$LOG"
    fi
}

run_test llama_cpp 0-15 \
    "$ROOT/workloads/llama_cpp/run_llama_native.sh"

run_test bert 0-15 \
    env OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
    "$ROOT/.venv/bin/python" \
    "$ROOT/workloads/bert/run_bert_native.py"

run_test dlrm 0-15 \
    env OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
    "$ROOT/.venv/bin/python" \
    "$ROOT/workloads/embedding_recommendation/dlrm/dlrm_s_pytorch.py" \
    --data-generation=random \
    --mini-batch-size=32 \
    --num-batches=100 \
    --arch-embedding-size="1000000-1000000-1000000-1000000" \
    --arch-sparse-feature-size=64 \
    --arch-mlp-bot="512-256-64" \
    --arch-mlp-top="256-128-1" \
    --num-indices-per-lookup-fixed=10 \
    --inference-only \
    --print-freq=10 \
    --print-time \
    --print-wall-time

run_test ann 0-15 \
    "$ROOT/workloads/ann/ann_benchmark"

run_test stream 0-15 \
    env OMP_NUM_THREADS=8 OMP_PROC_BIND=close OMP_PLACES=cores \
    "$ROOT/workloads/STREAM/stream"

run_test pointer_chase 0 \
    "$ROOT/workloads/pointer_chase/multichase/multichase" \
    -m 512M -n 5 -t 1 -c simple -a

run_test kmeans 0-15 \
    env OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 \
    "$ROOT/.venv/bin/python" \
    "$ROOT/workloads/kmeans/run_kmeans_native.py"

echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "Validation finished: $(date)" | tee -a "$LOG"
