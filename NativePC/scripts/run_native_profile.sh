#!/usr/bin/env bash
set -u

if [ "$#" -lt 3 ]; then
    echo "Usage: $0 <workload_name> <cpu_affinity> <command...>"
    exit 2
fi

WORKLOAD="$1"
CPU_AFFINITY="$2"
shift 2

RUN_ID="$(date +%Y%m%d_%H%M%S)_${WORKLOAD}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$ROOT/raw_data/${WORKLOAD}/native/${RUN_ID}"
mkdir -p "$BASE"

META="$BASE/metadata.txt"
CMD="$(printf '%q ' "$@")"

CPU_MODEL="$(lscpu | awk -F: '$1 ~ /^Model name[[:space:]]*$/ {gsub(/^[[:space:]]+/, "", $2); print $2; exit}')"

{
    echo "run_id=$RUN_ID"
    echo "workload=$WORKLOAD"
    echo "date=$(date --iso-8601=seconds)"
    echo "command=$CMD"
    echo "hostname=$(hostname)"
    echo "kernel=$(uname -r)"
    echo "cpu_model=$CPU_MODEL"
    echo "cpu_affinity=$CPU_AFFINITY"
    echo "governor=$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo unknown)"
    echo "turbo_no_turbo=$(cat /sys/devices/system/cpu/intel_pstate/no_turbo 2>/dev/null || echo unknown)"
    echo "perf_paranoid=$(cat /proc/sys/kernel/perf_event_paranoid)"
    echo "nmi_watchdog=$(cat /proc/sys/kernel/nmi_watchdog)"
    echo "memory=$(free -h | awk '/^Mem:/ {print $2}')"
} > "$META"

printf '%s\n' "$CMD" > "$BASE/command.txt"

# -------------------------
# Group 1: core + cache
# -------------------------
perf stat -x, -o "$BASE/core_cache.csv" \
    -e cpu_core/cycles/ \
    -e cpu_core/instructions/ \
    -e cpu_core/cache-references/ \
    -e cpu_core/cache-misses/ \
    -e cpu_core/l2_rqsts.all_demand_data_rd/ \
    -e cpu_core/l2_rqsts.demand_data_rd_miss/ \
    taskset -c "$CPU_AFFINITY" "$@" \
    > "$BASE/stdout_core_cache.log" \
    2> "$BASE/stderr_core_cache.log"
RC1=$?

# -------------------------
# Group 2a: memory traffic + outstanding reads
# -------------------------
perf stat -x, -o "$BASE/memory_traffic.csv" \
    -e cpu_core/cycles/ \
    -e cpu_core/instructions/ \
    -e cpu_core/mem-loads/ \
    -e cpu_core/mem-stores/ \
    -e cpu_core/offcore_requests_outstanding.cycles_with_data_rd/ \
    taskset -c "$CPU_AFFINITY" "$@" \
    > "$BASE/stdout_memory_traffic.log" \
    2> "$BASE/stderr_memory_traffic.log"
RC2A=$?

# -------------------------
# Group 2b: top-down memory bound
# -------------------------
perf stat -x, -o "$BASE/topdown_mem_bound.csv" \
    -e cpu_core/cycles/ \
    -e cpu_core/instructions/ \
    -e cpu_core/slots/ \
    -e cpu_core/topdown-mem-bound/ \
    taskset -c "$CPU_AFFINITY" "$@" \
    > "$BASE/stdout_topdown_mem_bound.log" \
    2> "$BASE/stderr_topdown_mem_bound.log"
RC2B=$?

# -------------------------
# Group 2c: top-down backend bound
# -------------------------
perf stat -x, -o "$BASE/topdown_backend_bound.csv" \
    -e cpu_core/cycles/ \
    -e cpu_core/instructions/ \
    -e cpu_core/slots/ \
    -e cpu_core/topdown-be-bound/ \
    taskset -c "$CPU_AFFINITY" "$@" \
    > "$BASE/stdout_topdown_backend_bound.log" \
    2> "$BASE/stderr_topdown_backend_bound.log"
RC2C=$?

# -------------------------
# Group 3: retired memory
# -------------------------
perf stat -x, -o "$BASE/memory_retired.csv" \
    -e cpu_core/cycles/ \
    -e cpu_core/instructions/ \
    -e cpu_core/mem_load_retired.l1_miss/ \
    -e cpu_core/mem_load_retired.l2_miss/ \
    -e cpu_core/mem_load_retired.l3_miss/ \
    taskset -c "$CPU_AFFINITY" "$@" \
    > "$BASE/stdout_memory_retired.log" \
    2> "$BASE/stderr_memory_retired.log"
RC3=$?

# -------------------------
# Group 4: TLB
# -------------------------
perf stat -x, -o "$BASE/tlb.csv" \
    -e cpu_core/cycles/ \
    -e cpu_core/instructions/ \
    -e cpu_core/dtlb_load_misses.walk_completed/ \
    -e cpu_core/dtlb_store_misses.walk_completed/ \
    taskset -c "$CPU_AFFINITY" "$@" \
    > "$BASE/stdout_tlb.log" \
    2> "$BASE/stderr_tlb.log"
RC4=$?

printf 'group,return_code\ncore_cache,%s\nmemory_traffic,%s\ntopdown_mem_bound,%s\ntopdown_backend_bound,%s\nmemory_retired,%s\ntlb,%s\n' \
    "$RC1" "$RC2A" "$RC2B" "$RC2C" "$RC3" "$RC4" > "$BASE/status.csv"

echo "RAW_RUN_DIR=$BASE"

if [ "$RC1" -ne 0 ] || [ "$RC2A" -ne 0 ] || [ "$RC2B" -ne 0 ] || [ "$RC2C" -ne 0 ] || [ "$RC3" -ne 0 ] || [ "$RC4" -ne 0 ]; then
    exit 1
fi

exit 0
