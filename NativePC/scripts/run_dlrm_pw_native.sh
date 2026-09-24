#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
DLRM="$ROOT/workloads/embedding_recommendation/dlrm/dlrm_s_pytorch.py"

CPU_AFFINITY="${CPU_AFFINITY:-0}"
TABLES="${DLRM_TABLES:-4}"
ROWS_PER_TABLE="${DLRM_ROWS_PER_TABLE:-1000000}"
EMBEDDING_DIM="${DLRM_EMBEDDING_DIM:-64}"
BATCH_SIZE="${DLRM_BATCH_SIZE:-32}"
NUM_BATCHES="${DLRM_NUM_BATCHES:-100}"
LOOKUPS="${DLRM_LOOKUPS:-10}"

if [[ ! -x "$PYTHON" ]]; then
    echo "Missing virtual-environment Python: $PYTHON" >&2
    exit 1
fi

if [[ ! -f "$DLRM" ]]; then
    echo "Missing DLRM entry point: $DLRM" >&2
    exit 1
fi

if ! [[ "$TABLES" =~ ^[1-9][0-9]*$ && "$ROWS_PER_TABLE" =~ ^[1-9][0-9]*$ ]]; then
    echo "DLRM_TABLES and DLRM_ROWS_PER_TABLE must be positive integers." >&2
    exit 2
fi

if ! perf stat -e cpu_core/cycles/ -- taskset -c "$CPU_AFFINITY" true \
    >/dev/null 2>&1; then
    echo "The CPU performance counters are unavailable to this user." >&2
    echo "On this host, run this script with sudo (perf_event_paranoid is 4)." >&2
    echo "Use CPU_AFFINITY=0..15; CPUs 16..19 are E-cores without cpu_core events." >&2
    exit 1
fi

EMBEDDING_SIZES="$ROWS_PER_TABLE"
for ((i = 1; i < TABLES; i++)); do
    EMBEDDING_SIZES+="-$ROWS_PER_TABLE"
done

RUN_ID="$(date +%Y%m%d_%H%M%S)_dlrm_pw"
OUT_DIR="$ROOT/raw_data/dlrm/native_pw/$RUN_ID"
PERF_CSV="$OUT_DIR/perf.csv"
SUMMARY="$OUT_DIR/summary.txt"
mkdir -p "$OUT_DIR"

CMD=(
    env
    OMP_NUM_THREADS=1
    MKL_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    VECLIB_MAXIMUM_THREADS=1
    "$PYTHON" "$DLRM"
    --data-generation=random
    --mini-batch-size="$BATCH_SIZE"
    --num-batches="$NUM_BATCHES"
    --arch-embedding-size="$EMBEDDING_SIZES"
    --arch-sparse-feature-size="$EMBEDDING_DIM"
    --arch-mlp-bot="512-256-$EMBEDDING_DIM"
    --arch-mlp-top="256-128-1"
    --num-indices-per-lookup="$LOOKUPS"
    --num-indices-per-lookup-fixed=True
    --inference-only
    --print-freq=10
    --print-time
    --print-wall-time
    --report-phase-times
)

{
    echo "run_id=$RUN_ID"
    echo "cpu_affinity=$CPU_AFFINITY"
    echo "tables=$TABLES"
    echo "rows_per_table=$ROWS_PER_TABLE"
    echo "embedding_dimension=$EMBEDDING_DIM"
    echo "batch_size=$BATCH_SIZE"
    echo "num_batches=$NUM_BATCHES"
    echo "lookups_per_table=$LOOKUPS"
    printf 'command='
    printf '%q ' "${CMD[@]}"
    printf '\n'
} > "$OUT_DIR/metadata.txt"

echo "Native DLRM page-walk measurement"
echo "Output: $OUT_DIR"
echo "CPU: $CPU_AFFINITY (one logical P-core by default)"
echo "Embedding tables: $TABLES x $ROWS_PER_TABLE rows x $EMBEDDING_DIM float32 values"

perf stat -x, -o "$PERF_CSV" \
    -e cpu_core/cycles/ \
    -e cpu_core/dtlb_load_misses.walk_active/ \
    -e cpu_core/dtlb_store_misses.walk_active/ \
    -- taskset -c "$CPU_AFFINITY" "${CMD[@]}" \
    > "$OUT_DIR/stdout.log" \
    2> "$OUT_DIR/stderr.log"

awk -F, '
    $3 == "cpu_core/cycles/" { cycles = $1; cycles_running = $5 }
    $3 == "cpu_core/dtlb_load_misses.walk_active/" {
        load = $1; load_running = $5
    }
    $3 == "cpu_core/dtlb_store_misses.walk_active/" {
        store = $1; store_running = $5
    }
    END {
        gsub(/[[:space:]]/, "", cycles)
        gsub(/[[:space:]]/, "", load)
        gsub(/[[:space:]]/, "", store)
        if (cycles !~ /^[0-9.]+$/ || load !~ /^[0-9.]+$/ ||
            store !~ /^[0-9.]+$/ || cycles == 0) {
            print "Could not parse perf counters; inspect perf.csv and stderr.log."
            exit 1
        }

        lower = (load > store ? load : store)
        upper = load + store
        if (upper > cycles) upper = cycles

        printf "cycles=%.0f\n", cycles
        printf "dtlb_load_walk_active_cycles=%.0f\n", load
        printf "dtlb_store_walk_active_cycles=%.0f\n", store
        printf "dtlb_load_pw_percent=%.6f\n", 100.0 * load / cycles
        printf "dtlb_store_pw_percent=%.6f\n", 100.0 * store / cycles
        printf "combined_pw_percent_lower_bound=%.6f\n", 100.0 * lower / cycles
        printf "combined_pw_percent_upper_bound=%.6f\n", 100.0 * upper / cycles
        printf "cycles_counter_scheduled_percent=%s\n", cycles_running
        printf "load_counter_scheduled_percent=%s\n", load_running
        printf "store_counter_scheduled_percent=%s\n", store_running
        print "note_perf_schedule=The scheduled percentages are perf counter coverage, not PW%."
        print "note=The exact load/store union is not recoverable from aggregate hardware counters."
    }
' "$PERF_CSV" | tee "$SUMMARY"

PHASE_TIMING="$(grep '^DLRM_PHASE ' "$OUT_DIR/stdout.log" || true)"
if [[ -n "$PHASE_TIMING" ]]; then
    {
        echo
        echo "DLRM phase timing"
        printf '%s\n' "$PHASE_TIMING"
        echo "note_timing=Native phase durations must not be multiplied by gem5 host/simulated-time slowdown; measure the ROI after the KVM-to-Timing switch."
    } | tee -a "$SUMMARY"
fi

echo "SUMMARY=$SUMMARY"
