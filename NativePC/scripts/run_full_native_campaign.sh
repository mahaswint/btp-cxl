#!/usr/bin/env bash
set -u

ROOT="$HOME/BTP_CXL_Study"
REPS=5
LOG="$ROOT/raw_data/full_native_campaign.log"

mkdir -p "$ROOT/raw_data"

run_workload() {
    echo "========================================" | tee -a "$LOG"
    echo "START: $1" | tee -a "$LOG"
    date | tee -a "$LOG"

    "$ROOT/scripts/run_repeated_native.sh" "$@" >> "$LOG" 2>&1
    RC=$?

    echo "END: $1 rc=$RC" | tee -a "$LOG"
    date | tee -a "$LOG"

    return "$RC"
}

echo "BTP FULL NATIVE CAMPAIGN" | tee "$LOG"
echo "Started: $(date)" | tee -a "$LOG"

run_workload llama_cpp 0-15 "$REPS" \
    "$ROOT/workloads/llama_cpp/run_llama_native.sh" || exit 1

run_workload bert 0-15 "$REPS" \
    env OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 \
    "$ROOT/.venv/bin/python" \
    "$ROOT/workloads/bert/run_bert_native.py" || exit 1

run_workload dlrm 0-15 "$REPS" \
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
    --print-wall-time || exit 1

run_workload ann 0-15 "$REPS" \
    "$ROOT/workloads/ann/ann_benchmark" || exit 1

run_workload stream 0-15 "$REPS" \
    env OMP_NUM_THREADS=8 OMP_PROC_BIND=close OMP_PLACES=cores \
    "$ROOT/workloads/STREAM/stream" || exit 1

run_workload pointer_chase 0 "$REPS" \
    "$ROOT/workloads/pointer_chase/multichase/multichase" \
    -m 512M -n 5 -t 1 -c simple -a || exit 1

run_workload kmeans 0-15 "$REPS" \
    env OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 \
    "$ROOT/.venv/bin/python" \
    "$ROOT/workloads/kmeans/run_kmeans_native.py" || exit 1

echo "========================================" | tee -a "$LOG"
echo "FULL CAMPAIGN COMPLETED: $(date)" | tee -a "$LOG"
