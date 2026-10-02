#!/usr/bin/env bash
set -u

if [ "$#" -lt 4 ]; then
    echo "Usage: $0 <workload> <cpu_affinity> <repetitions> <command...>"
    exit 2
fi

WORKLOAD="$1"
CPU_AFFINITY="$2"
REPS="$3"
shift 3

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$ROOT/raw_data/${WORKLOAD}/native_campaign"
mkdir -p "$BASE"

MASTER_LOG="$BASE/campaign.log"
MASTER_STATUS="$BASE/campaign_status.csv"

echo "repetition,timestamp,status,raw_dir" > "$MASTER_STATUS"

for ((i=1; i<=REPS; i++)); do
    echo "========================================" | tee -a "$MASTER_LOG"
    echo "Starting $WORKLOAD repetition $i/$REPS" | tee -a "$MASTER_LOG"
    date | tee -a "$MASTER_LOG"

    BEFORE_COUNT=$(find "$ROOT/raw_data/${WORKLOAD}/native" \
        -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)

    if "$ROOT/scripts/run_native_profile.sh" \
        "$WORKLOAD" \
        "$CPU_AFFINITY" \
        "$@"; then
        STATUS="SUCCESS"
    else
        STATUS="FAILED"
    fi

    AFTER_DIR=$(find "$ROOT/raw_data/${WORKLOAD}/native" \
        -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)

    echo "${i},$(date --iso-8601=seconds),${STATUS},${AFTER_DIR}" \
        >> "$MASTER_STATUS"

    echo "Finished repetition $i: $STATUS" | tee -a "$MASTER_LOG"

    if [ "$STATUS" != "SUCCESS" ]; then
        echo "Stopping campaign because a repetition failed." | tee -a "$MASTER_LOG"
        exit 1
    fi
done

echo "Campaign completed successfully." | tee -a "$MASTER_LOG"
