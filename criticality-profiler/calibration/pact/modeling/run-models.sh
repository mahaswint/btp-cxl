#!/bin/bash

# run-models.sh — Collect perf counters across three memory tiers and
# produce the CSV file read by corr.plot for Figure 3.


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RAW_DIR="${SCRIPT_DIR}/raw"              # raw perf stat output files
OUTPUT_CSV="${RAW_DIR}/models.csv"       # collected results CSV

# NUMA topology — adjust for your server (check with: numactl --hardware)
CPU_NODE=0      # CPU execution node
LOCAL_NODE=0    # Tier 1: local DRAM   (~90ns)
NUMA_NODE=1     # Tier 2: remote NUMA  (~140ns)
CXL_NODE=2      # Tier 3: CXL          (~190ns)

# Stock perf is enough — the four counters below are read from perf stat text
# output. Override with: PERF=/path/to/perf ./run-models.sh (default: perf in PATH)
PERF="${PERF:-perf}"

# Four perf counters; all collected in a single perf stat pass
PERF_EVENTS="CYCLE_ACTIVITY.STALLS_L3_MISS"
PERF_EVENTS+=",MEM_LOAD_RETIRED.L3_MISS"
PERF_EVENTS+=",OFFCORE_REQUESTS_OUTSTANDING.DEMAND_DATA_RD"
PERF_EVENTS+=",OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DEMAND_DATA_RD"

export OMP_NUM_THREADS=8


# ── workloads ──────────────────────────────────────────────────────────────────

# SPEC CPU 2017 — point SPEC_DIR at your (licensed) SPEC CPU 2017 install.
# Override with: SPEC_DIR=/path/to/cpu2017 ./run-models.sh
SPEC_DIR="${SPEC_DIR:-/path/to/cpu2017}"
SPEC_MCF_DIR="${SPEC_DIR}/505.mcf_r"

SPEC_WORKLOADS=(
    "505.mcf_r|cd ${SPEC_MCF_DIR} && ./mcf_r_base.mytest-m64 inp.in"
)

# GAP benchmark suite — point GAPBS_DIR at your gapbs build (see README).
# Override with: GAPBS_DIR=/path/to/gapbs ./run-models.sh
GAPBS_DIR="${GAPBS_DIR:-/path/to/gapbs}"
GAPBS_GRAPH_DIR="${GAPBS_DIR}/benchmark/graphs"
# vmtouch preloads the graph into the page cache. Override with:
# VMTOUCH=/path/to/vmtouch ./run-models.sh   (default: vmtouch in PATH)
VMTOUCH="${VMTOUCH:-vmtouch}"

GAPBS_WORKLOADS=(
    "bc-kron"
)


# ── argument parsing ───────────────────────────────────────────────────────────

RUN_SPEC=false
RUN_GAPBS=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --spec)       RUN_SPEC=true;           shift   ;;
        --gapbs)      RUN_GAPBS=true;          shift   ;;
        --output)     OUTPUT_CSV="$2";         shift 2 ;;
        --raw-dir)    RAW_DIR="$2";            shift 2 ;;
        --local-node) LOCAL_NODE="$2";         shift 2 ;;
        --numa-node)  NUMA_NODE="$2";          shift 2 ;;
        --cxl-node)   CXL_NODE="$2";           shift 2 ;;
        --cpu-node)   CPU_NODE="$2";           shift 2 ;;
        *) echo "unknown option: $1"; exit 1 ;;
    esac
done

[[ "${RUN_SPEC}" == false && "${RUN_GAPBS}" == false ]] && \
    echo "usage: $0 --spec | --gapbs | --spec --gapbs" && exit 1

# skip a tier if its NUMA node does not exist on this machine
NUMA_AVAILABLE=true
CXL_AVAILABLE=true
[[ ! -d "/sys/devices/system/node/node${NUMA_NODE}" ]] && NUMA_AVAILABLE=false
[[ ! -d "/sys/devices/system/node/node${CXL_NODE}"  ]] && CXL_AVAILABLE=false


# ── helpers ────────────────────────────────────────────────────────────────────

func_run_spec_tier() {
    local name="$1" cmd="$2" node="$3" tier="$4"
    local outfile="${RAW_DIR}/${name}_${tier}.txt"

    echo "    [${tier}]  node=${node}  →  $(basename "${outfile}")"

    numactl --cpunodebind="${CPU_NODE}" --membind="${node}" -- \
        ${PERF} stat -e "${PERF_EVENTS}" \
                  -o "${outfile}" \
                  -- bash -c "${cmd}" 2>/dev/null \
        || echo "    WARNING: perf failed for ${name}/${tier}"
}

func_run_gapbs_tier() {
    local name="$1" node="$2" tier="$3"
    local outfile="${RAW_DIR}/${name}_${tier}.txt"

    echo "    [${tier}]  node=${node}  →  $(basename "${outfile}")"

    local GRAPH_DATASET="kron.sg"
    echo "    => Loading graph into page cache first"
    numactl --cpunodebind="${CPU_NODE}" --membind="${node}" \
        ${VMTOUCH} -f -t ${GAPBS_GRAPH_DIR}/${GRAPH_DATASET} -m 64G
    sleep 20

    local BENCH_CMD="${GAPBS_DIR}/bc -f ${GAPBS_GRAPH_DIR}/kron.sg -i4 -n4"
    echo "    => ${BENCH_CMD}"
    export OMP_NUM_THREADS

    numactl --cpunodebind="${CPU_NODE}" --membind="${node}" -- \
        ${PERF} stat -e "${PERF_EVENTS}" \
                  -o "${outfile}" \
                  -- bash -c "${BENCH_CMD}" 2>/dev/null \
        || echo "    WARNING: perf failed for ${name}/${tier}"
}

# Extract an integer counter from a perf stat -o file; returns 0 if missing.
func_extract_int() {
    local file="$1" pattern="$2"
    grep -i "${pattern}" "${file}" 2>/dev/null \
        | head -1 \
        | awk '{ gsub(",", "", $1); printf "%.0f\n", $1+0 }'
}

# Parse one raw perf file → echo "l3_stall  l3_miss  mlp  llc_miss_mlp"
# MLP          = DEMAND_DATA_RD / CYCLES_WITH_DEMAND_DATA_RD
# llc_miss_mlp = l3_miss / MLP  (columns 15/16/17 in CSV, plotted by corr.plot)
func_parse_tier_file() {
    local file="$1"

    [[ ! -f "${file}" ]] && echo "0 0 0 0" && return

    local stall miss outstanding outstanding_cyc

    stall=$(func_extract_int "${file}" "cycle_activity\.stalls_l3_miss")
    miss=$(func_extract_int  "${file}" "mem_load_retired\.l3_miss")

    # grep -v to distinguish .demand_data_rd from .cycles_with_demand_data_rd
    outstanding=$(grep -i "offcore_requests_outstanding\.demand_data_rd" "${file}" 2>/dev/null \
                      | grep -iv "cycles_with" \
                      | head -1 \
                      | awk '{ gsub(",", "", $1); printf "%.0f\n", $1+0 }')
    outstanding=${outstanding:-0}

    outstanding_cyc=$(func_extract_int "${file}" \
                          "offcore_requests_outstanding\.cycles_with_demand_data_rd")

    awk -v stall="${stall:-0}" \
        -v miss="${miss:-0}" \
        -v out="${outstanding:-0}" \
        -v cyc="${outstanding_cyc:-0}" \
        'BEGIN {
            mlp          = (cyc > 0) ? out / cyc : 1.0
            llc_miss_mlp = (mlp > 0) ? miss / mlp : miss
            printf "%.0f %.0f %.6f %.6f\n", stall, miss, mlp, llc_miss_mlp
        }'
}


# ── collect ────────────────────────────────────────────────────────────────────

func_collect() {
    echo "==> Collecting perf counters"
    echo ""

    local count=0

    if [[ "${RUN_SPEC}" == true ]]; then
        for entry in "${SPEC_WORKLOADS[@]}"; do
            local name="${entry%%|*}"
            local cmd="${entry#*|}"

            echo "  [${name}]"
            func_run_spec_tier "${name}" "${cmd}" "${LOCAL_NODE}" "local"
            [[ "${NUMA_AVAILABLE}" == true ]] && \
                func_run_spec_tier "${name}" "${cmd}" "${NUMA_NODE}" "remote_numa"
            [[ "${CXL_AVAILABLE}" == true ]] && \
                func_run_spec_tier "${name}" "${cmd}" "${CXL_NODE}"  "cxl"
            echo ""
            count=$((count + 1))
        done
    fi

    if [[ "${RUN_GAPBS}" == true ]]; then
        for name in "${GAPBS_WORKLOADS[@]}"; do
            echo "  [${name}]"
            func_run_gapbs_tier "${name}" "${LOCAL_NODE}" "local"
            [[ "${NUMA_AVAILABLE}" == true ]] && \
                func_run_gapbs_tier "${name}" "${NUMA_NODE}" "remote_numa"
            [[ "${CXL_AVAILABLE}" == true ]] && \
                func_run_gapbs_tier "${name}" "${CXL_NODE}"  "cxl"
            echo ""
            count=$((count + 1))
        done
    fi

    echo "==> Collected ${count} workload(s)"
    echo ""
}




func_write_csv() {
    echo "==> Writing CSV → ${OUTPUT_CSV}"

    if [[ ! -f "${OUTPUT_CSV}" ]]; then
        {
            printf ",workload,"
            printf "l3_stall_1,l3_stall_2,l3_stall_3,"
            printf "demand_l2_mlp_1,demand_l2_mlp_2,demand_l2_mlp_3,"
            printf "l3_miss_1,l3_miss_2,l3_miss_3,"
            printf "offcore_load_latency_1,offcore_load_latency_2,offcore_load_latency_3,"
            printf "(l3_miss/mlp)_1,(l3_miss/mlp)_2,(l3_miss/mlp)_3,"
            printf "(lat*l3_miss/mlp)_1,(lat*l3_miss/mlp)_2,(lat*l3_miss/mlp)_3\n"
        } > "${OUTPUT_CSV}"
    fi

    local idx skipped=0
    # Row index = count of data rows already in the CSV. grep -c prints "0" AND
    # exits 1 on a header-only file, so `|| echo 0` would make idx="0\n0" and
    # break the printf/arithmetic below; capture then default instead.
    idx=$(grep -c "^[0-9]" "${OUTPUT_CSV}" 2>/dev/null) || true
    idx=${idx:-0}

    local all_names=()
    [[ "${RUN_SPEC}"  == true ]] && for entry in "${SPEC_WORKLOADS[@]}";  do all_names+=("${entry%%|*}"); done
    [[ "${RUN_GAPBS}" == true ]] && for name  in "${GAPBS_WORKLOADS[@]}"; do all_names+=("${name}"); done

    for name in "${all_names[@]}"; do
        local f1="${RAW_DIR}/${name}_local.txt"
        local f2="${RAW_DIR}/${name}_remote_numa.txt"
        local f3="${RAW_DIR}/${name}_cxl.txt"

        if [[ ! -f "${f1}" && ! -f "${f2}" && ! -f "${f3}" ]]; then
            echo "  skip ${name}: no raw files in ${RAW_DIR}/"
            skipped=$((skipped + 1))
            continue
        fi

        read -r stall1 miss1 mlp1 llc_miss_mlp1 <<< "$(func_parse_tier_file "${f1}")"
        read -r stall2 miss2 mlp2 llc_miss_mlp2 <<< "$(func_parse_tier_file "${f2}")"
        read -r stall3 miss3 mlp3 llc_miss_mlp3 <<< "$(func_parse_tier_file "${f3}")"

        printf "%d,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0,0,%s,%s,%s,0,0,0\n" \
            "${idx}" "${name}" \
            "${stall1}" "${stall2}" "${stall3}" \
            "${mlp1}"   "${mlp2}"   "${mlp3}"   \
            "${miss1}"  "${miss2}"  "${miss3}"  \
            "${llc_miss_mlp1}" "${llc_miss_mlp2}" "${llc_miss_mlp3}" \
            >> "${OUTPUT_CSV}"

        echo "  [${idx}] ${name}"
        idx=$((idx + 1))
    done

    echo ""
    echo "==> Done: ${idx} workload(s) written to ${OUTPUT_CSV}"
    [[ "${skipped}" -gt 0 ]] && echo "    (${skipped} skipped — raw files missing)"
}


# ── main ───────────────────────────────────────────────────────────────────────

func_main() {
    echo "run-models.sh"
    echo "  CPU node:      ${CPU_NODE}"
    echo "  Tier 1 local:  node ${LOCAL_NODE}  (~90ns)"
    echo "  Tier 2 NUMA:   node ${NUMA_NODE}  (~140ns)  $( [[ "${NUMA_AVAILABLE}" == false ]] && printf "[SKIPPED — node not found]" )"
    echo "  Tier 3 CXL:    node ${CXL_NODE}  (~190ns)  $( [[ "${CXL_AVAILABLE}" == false ]] && printf "[SKIPPED — node not found]" )"
    echo "  Suites:        $( [[ "${RUN_SPEC}" == true ]] && printf "SPEC "; [[ "${RUN_GAPBS}" == true ]] && printf "GAPBS" )"
    echo "  Raw dir:       ${RAW_DIR}/"
    echo "  Output CSV:    ${OUTPUT_CSV}"
    echo ""

    mkdir -p "${RAW_DIR}"

    func_collect

    func_write_csv

    echo ""
    echo "  Output CSV:    ${OUTPUT_CSV}"
    echo "  To plot:       cp ${OUTPUT_CSV} ${SCRIPT_DIR}/skx/dat/r-l3_stall_skx.csv"
    echo "                 cd ${SCRIPT_DIR}/skx && gnuplot plot/corr.plot"
}

echo "run ..."
func_main
echo "Done"
