#!/usr/bin/env bash
# Run inside libguestfs, with all simulations using this image stopped.
set -euo pipefail
jobs=${1:-2}
export PATH=/opt/btp/venv/bin:/usr/bin:/bin
test -f /opt/btp/build/llama/CMakeCache.txt
cmake -S /opt/btp/upstreams/llama_cpp -B /opt/btp/build/llama \
    -DGGML_NATIVE=OFF -DGGML_BMI2=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF \
    -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_AVX512=OFF
cmake --build /opt/btp/build/llama --target llama-cli -j"$jobs"
ln -sfn /opt/btp/build/llama/bin/llama-cli /opt/btp/bin/llama-cli
grep -q '^GGML_BMI2:BOOL=OFF$' /opt/btp/build/llama/CMakeCache.txt
echo 'Rebuilt llama-cli with BMI2 disabled; simulator validation remains required.'
