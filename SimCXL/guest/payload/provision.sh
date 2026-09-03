#!/usr/bin/env bash
# Runs inside the offline guest appliance, never in the host root filesystem.
set -euo pipefail
profile=${1:-basic}
jobs=${2:-2}
stage=${3:-full}
[[ "$stage" == full || ( "$stage" == models && "$profile" == all ) ]] || {
    echo 'Provision stage must be full, or models with profile all' >&2; exit 1;
}
test -d /opt/btp/simcxl/util/m5
if [[ "$stage" == models ]]; then
    for executable in m5 phase memory_pilot stream multichase ann_benchmark llama-cli; do
        [[ -x "/opt/btp/bin/$executable" ]] || {
            echo "Missing $executable; rerun full preparation before using --models-only" >&2; exit 1;
        }
    done
    /opt/btp/venv/bin/pip check
    echo 'Resuming at model downloads; skipping package installation and all compilation'
fi
export DEBIAN_FRONTEND=noninteractive
# Repair the appliance network before trying DNS or installing packages.
bash /opt/btp/configure-network.sh
# Use QEMU's DNS forwarder, which can reach the host resolver.
bash /opt/btp/configure-resolver.sh /opt/btp/config/provision-resolv.conf \
    /etc/resolv.conf /opt/btp/config/resolv.conf.before-provision
# The upstream image mixes bionic and focal repositories. Match its actual OS.
if [[ "$stage" == full ]]; then
. /etc/os-release
if [[ "$ID" != ubuntu || ! "${VERSION_CODENAME:-}" =~ ^[a-z]+$ ]]; then
    echo 'Guest provisioning requires Ubuntu with VERSION_CODENAME set' >&2
    exit 1
fi
backup=/opt/btp/config/apt-before-provision
mkdir -p "$backup"
if [[ -e /etc/apt/sources.list && ! -e "$backup/sources.list" ]]; then
    cp -a /etc/apt/sources.list "$backup/"
fi
if [[ -d /etc/apt/sources.list.d && ! -e "$backup/sources.list.d" ]]; then
    mv /etc/apt/sources.list.d "$backup/"
fi
mkdir -p /etc/apt/sources.list.d
cat > /etc/apt/sources.list <<EOF
deb http://archive.ubuntu.com/ubuntu $VERSION_CODENAME main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu $VERSION_CODENAME-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu $VERSION_CODENAME-security main restricted universe multiverse
EOF
# Discard stale cross-release index selection while preserving it for diagnosis.
if [[ -d /var/lib/apt/lists && ! -e "$backup/lists" ]]; then
    mv /var/lib/apt/lists "$backup/lists"
fi
mkdir -p /var/lib/apt/lists/partial
for host in archive.ubuntu.com security.ubuntu.com; do
    if ! timeout 15s getent ahostsv4 "$host" >/dev/null; then
        echo "Guest DNS failed for $host; check SIMCXL_DNS_NAMESERVERS on the host" >&2
        exit 1
    fi
done
# Older apt can exit zero after failed downloads. Reject those warnings too.
LC_ALL=C apt-get -o Acquire::Retries=1 -o Acquire::http::Timeout=20 update 2>&1 | tee /tmp/simcxl-apt-update.log
if grep -Eq '^(Err:|W: Failed to fetch|W: Some index files|E:)' /tmp/simcxl-apt-update.log; then
    echo 'Package index download failed; stopping before installation' >&2
    exit 1
fi
apt-get install -y --no-install-recommends build-essential scons python3 python3-venv \
    python3-pip numactl libnuma-dev ca-certificates git cmake pkg-config perl kmod udev
mkdir -p /opt/btp/bin /opt/btp/models /opt/btp/results
cd /opt/btp/simcxl/util/m5
scons -j"$jobs" build/x86/out/m5 build/x86/out/libm5.a
install -m755 build/x86/out/m5 /opt/btp/bin/m5
gcc -O2 -I/opt/btp/simcxl/include /opt/btp/src/phase.c \
    build/x86/out/libm5.a -o /opt/btp/bin/phase
cd /opt/btp
# Conservative x86 code generation for gem5's modeled ISA; no host -march=native.
gcc -O2 -march=x86-64 src/memory_pilot.c -o bin/memory_pilot
gcc -O2 -march=x86-64 -fopenmp -DSTREAM_ARRAY_SIZE=50000000 -DNTIMES=20 \
    upstreams/stream/stream.c -o bin/stream
make -C upstreams/pointer_chase -j"$jobs" multichase
install -m755 upstreams/pointer_chase/multichase bin/multichase
if [[ "$profile" == all ]]; then
    apt-get install -y --no-install-recommends libopenblas-dev liblapack-dev libssl-dev libcurl4-openssl-dev
    python3 -m venv /opt/btp/venv
    /opt/btp/venv/bin/pip install --upgrade 'pip==21.3.1' 'setuptools==59.6.0' 'wheel==0.37.1'
    # Resolve dependencies on PyPI first. The CPU-wheel index alone previously
    # caused pip to backtrack to torch 1.4, which lacks inference_mode.
    /opt/btp/venv/bin/pip install --only-binary=numpy,scipy,scikit-learn,cmake,tokenizers,grpcio \
        -r /opt/btp/config/requirements-all.txt
    /opt/btp/venv/bin/pip install --no-deps 'torch==1.10.2+cpu' --index-url https://download.pytorch.org/whl/cpu
    /opt/btp/venv/bin/pip check
    export PATH=/opt/btp/venv/bin:$PATH
    /opt/btp/venv/bin/python - <<'PY'
import torch
from transformers import AutoModel, AutoTokenizer
from sklearn.cluster import KMeans
from torch.utils.tensorboard import SummaryWriter
assert hasattr(torch, 'inference_mode'), 'BERT requires torch.inference_mode'
# sklearn 0.24 calls the Lloyd algorithm "full".
KMeans(n_clusters=1, n_init=1, algorithm='full').fit([[0.0], [1.0]])
print('Guest Python dependency checks passed; torch=' + torch.__version__)
PY
    cmake -S upstreams/llama_cpp -B /opt/btp/build/llama \
        -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF \
        -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_AVX512=OFF -DGGML_CUDA=OFF \
        -DGGML_BLAS=OFF -DLLAMA_BUILD_TESTS=OFF
    cmake --build /opt/btp/build/llama --target llama-cli -j"$jobs"
    ln -sfn /opt/btp/build/llama/bin/llama-cli /opt/btp/bin/llama-cli
    cmake -S upstreams/faiss -B /opt/btp/build/faiss \
        -DCMAKE_BUILD_TYPE=Release -DFAISS_ENABLE_GPU=OFF -DFAISS_ENABLE_PYTHON=OFF \
        -DFAISS_OPT_LEVEL=generic -DBUILD_TESTING=OFF
    cmake --build /opt/btp/build/faiss --target faiss -j"$jobs"
    # Match FAISS's C++20 headers; GCC 9 names that language mode c++2a.
    g++ -std=c++2a -O2 -march=x86-64 -fopenmp -Iupstreams/faiss src/ann_benchmark.cpp \
        /opt/btp/build/faiss/faiss/libfaiss.a -lopenblas -llapack -o bin/ann_benchmark
fi
fi
if [[ "$profile" == all ]]; then
    # Download once during image preparation; simulator runs are offline.
    export HF_HOME=/opt/btp/models/huggingface
    /opt/btp/venv/bin/python /opt/btp/download-models.py
    /opt/btp/venv/bin/pip freeze > /opt/btp/config/python-freeze.txt
fi
chmod 755 /opt/btp/boot.sh /opt/btp/run-workload.sh
printf '%s\n' "$profile" > /opt/btp/config/profile
uname -m > /opt/btp/config/provision-architecture
cp /etc/os-release /opt/btp/config/guest-os-release
dpkg-query -W > /opt/btp/config/packages.txt
printf 'Guest preparation completed (%s). No simulation has run yet.\n' "$profile"
