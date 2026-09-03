#!/usr/bin/env bash
set -euo pipefail
workload=${1:?workload required}
node=${2:-1}
threads=${3:-1}
size=${4:-full}
[[ "$size" == full || "$size" == smoke ]] || { echo 'Invalid workload size'; exit 2; }
export PATH=/opt/btp/bin:/opt/btp/venv/bin:/usr/bin:/bin
export OMP_NUM_THREADS="$threads" MKL_NUM_THREADS="$threads" OPENBLAS_NUM_THREADS="$threads"
export HF_HOME=/opt/btp/models/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
cd /opt/btp
# Refuse silent fallback to host DRAM if the CXL guest driver is not working.
[[ "$node" =~ ^[0-9]+$ ]] && [[ -d "/sys/devices/system/node/node$node" ]] || {
    echo "Requested NUMA node $node does not exist; CXL memory was not brought online."; exit 1;
}
case "$workload" in
    memory_pilot) command=(bin/memory_pilot 8) ;;
    stream) command=(bin/stream) ;;
    pointer_chase) command=(bin/multichase -m 512M -n 5 -t 1 -c simple -a) ;;
    ann) command=(bin/ann_benchmark) ;;
    bert) command=(venv/bin/python src/bert.py) ;;
    kmeans) command=(venv/bin/python src/kmeans.py) ;;
    llama_cpp) command=(bin/llama-cli -m models/llama/Llama-3.2-1B-Instruct-Q4_K_M.gguf
        -f src/fixed_prompt.txt -n 128 -t "$threads" -tb "$threads" --single-turn
        --simple-io --log-disable --no-display-prompt --temp 0 --no-mmap) ;;
    dlrm) command=(venv/bin/python upstreams/dlrm/dlrm_s_pytorch.py
        --data-generation=random --mini-batch-size=32 --num-batches=100
        --arch-embedding-size=1000000-1000000-1000000-1000000
        --arch-sparse-feature-size=64 --arch-mlp-bot=512-256-64 --arch-mlp-top=256-128-1
        --num-indices-per-lookup-fixed=10 --inference-only --print-freq=10 --print-time --print-wall-time) ;;
    gups) echo 'HPCC source is staged; its RandomAccess-only build/run configuration is still required.'; exit 2 ;;
    *) echo "Unknown workload: $workload"; exit 2 ;;
esac
if [[ "$size" == smoke ]]; then
    case "$workload" in
        memory_pilot) command=(bin/memory_pilot 1) ;;
        stream) command=(smoke/bin/stream) ;;
        pointer_chase) command=(smoke/bin/multichase -m 2M -n 1 -t 1 -c simple -a) ;;
        ann)
            export SIMCXL_ANN_VECTORS=1024 SIMCXL_ANN_QUERIES=8
            command=(smoke/bin/ann_benchmark) ;;
        bert)
            export SIMCXL_BERT_BATCH=1 SIMCXL_BERT_SEQUENCE=8 SIMCXL_BERT_WARMUP=0 SIMCXL_BERT_ITERATIONS=1
            command=(venv/bin/python smoke/src/bert.py) ;;
        kmeans)
            export SIMCXL_KMEANS_SAMPLES=512 SIMCXL_KMEANS_FEATURES=8 SIMCXL_KMEANS_CLUSTERS=4 SIMCXL_KMEANS_ITERATIONS=2
            command=(venv/bin/python smoke/src/kmeans.py) ;;
        dlrm) command=(venv/bin/python upstreams/dlrm/dlrm_s_pytorch.py --data-generation=random
            --mini-batch-size=2 --num-batches=2 --arch-embedding-size=1000-1000-1000-1000
            --arch-sparse-feature-size=16 --arch-mlp-bot=32-16 --arch-mlp-top=16-1
            --num-indices-per-lookup-fixed=2 --inference-only --print-freq=1 --print-time --print-wall-time) ;;
        llama_cpp) command=(bin/llama-cli -m models/llama/Llama-3.2-1B-Instruct-Q4_K_M.gguf
            -p Hello -n 2 -t "$threads" -tb "$threads" --single-turn --simple-io --log-disable
            --no-display-prompt --temp 0 --no-mmap) ;;
    esac
fi
[[ -x "${command[0]}" ]] || { echo 'Executable missing; prepare the image with the appropriate profile.'; exit 1; }
numactl --hardware > /tmp/numa.txt
printf 'workload=%s\nnuma_node=%s\nthreads=%s\n' "$workload" "$node" "$threads" > /tmp/workload-status.txt
printf 'workload_size=%s\n' "$size" >> /tmp/workload-status.txt
env | LC_ALL=C sort | grep '^SIMCXL_' >> /tmp/workload-status.txt || true
printf 'command=' >> /tmp/workload-status.txt
printf '%q ' "${command[@]}" >> /tmp/workload-status.txt
printf '\n' >> /tmp/workload-status.txt
phase begin workload
set +e
numactl --cpunodebind=0 --membind="$node" "${command[@]}" > /tmp/workload.log 2>&1
rc=$?
set -e
phase end workload
printf 'exit_code=%s\n' "$rc" >> /tmp/workload-status.txt
cat /tmp/workload.log
m5 --addr writefile /tmp/workload.log workload.log
m5 --addr writefile /tmp/workload-status.txt workload-status.txt
m5 --addr writefile /tmp/numa.txt numa.txt
exit "$rc"
