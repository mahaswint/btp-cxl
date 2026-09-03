# BTP guest environment

This directory keeps the full-system guest setup inside SimCXL. It uses the
[CXL-enabled kernel and disk image published by SimCXL](https://github.com/TianheMICALab/SimCXL#using-simcxl),
not the host operating system or the imported native Python environment.

The asset IDs and expected sizes are recorded in `assets.json`. The provided
kernel identifies itself as Linux 6.12.0+ and contains the patched CXL memory
initialization and `cxl_mem_driver`. The disk download is 4,972,248,228 bytes
compressed. The publisher does not supply a SHA-256 in its download listing;
the downloader validates format and expected size, then saves a local SHA-256
receipt for subsequent integrity checks. This local hash is not a publisher
signature.

## Layout and Git

```text
guest/
  assets.json             upstream kernel/disk identifiers
  upstreams.json          exact workload source revisions and repositories
  setup.py                download, source staging, and offline provisioning
  simulate.py             full-system SimCXL configuration
  run.py                  one workload plus CXL collection
  run_all.py              sequential workload suite, logs, and CSV/JSON manifest
  payload/                small tracked guest scripts and workload drivers
  images/                 ignored: kernel, archives, base/working disk, receipts
  local/                  ignored: staged upstream sources and build inputs
  results/                ignored: simulator output and measured results
```

Commit the setup scripts, manifests, small custom workload drivers, and existing
license notices to your BTP repository. Kernel/disk images, third-party source
archives, Python environments, model weights, checkpoints, and raw results stay
local. A new checkout can fetch the pinned upstream revisions with `setup.py
sources`; it does not need the original Downloads folder. To share selected
results later, export compact reports into a separately tracked directory.

The setup and workload commands do not change Git remotes or push code.

## Finish installation on this PC

Run from the SimCXL root. The kernel and local source archive may already be
staged; these commands preserve completed assets and do not launch a simulation.

```bash
sudo apt-get update
sudo apt-get install -y libguestfs-tools qemu-system-x86 qemu-utils git xz-utils
python3 guest/setup.py doctor
python3 guest/setup.py fetch
python3 guest/setup.py prepare --profile basic --jobs 2
```

`fetch` downloads the kernel and disk; existing verified assets are reused. An
interrupted transfer stays as `.part` and is never accepted as an image. This
version does not resume partial downloads: move the partial file aside before
retrying. Google Drive quota/sharing errors are reported rather than saved as
fake image files. The official [download folder](https://drive.google.com/drive/folders/1cwqsqxbZm9pCTW3QK33sZPVulQ8d9Lrl)
can also be inspected in a browser.

If `supermin exited with error status 1` occurs and `doctor` reports unreadable
host kernels, provide a readable copy and the matching installed modules.
For example, from the repository root (replace the version with one installed
under both `/boot` and `/lib/modules` on your PC):

```bash
mkdir -p guest/local
sudo install -m 0644 /boot/vmlinuz-6.17.0-14-generic guest/local/appliance-vmlinuz
export SUPERMIN_KERNEL="$PWD/guest/local/appliance-vmlinuz"
export SUPERMIN_MODULES=/lib/modules/6.17.0-14-generic
python3 guest/setup.py prepare --profile basic --jobs 2
```

These exports must be set in the terminal running setup. This host kernel is
only for libguestfs provisioning; simulation still uses `guest/images/vmlinux`.
The overrides are documented in the [supermin manual](https://libguestfs.org/supermin.1.html#ENVIRONMENT-VARIABLES).
If `btp.preparing.img` already exists, add `--resume` when retrying. If the failure persists,
collect a diagnostic log with
`LIBGUESTFS_BACKEND=direct libguestfs-test-tool > guest/local/libguestfs-test.log 2>&1`.

Package installation uses the direct backend's QEMU DNS forwarder at
`169.254.2.3`. If appliance DHCP leaves `eth0` without a default route, setup
configures its private address `169.254.2.15/16` and gateway `169.254.2.2`.
This only changes the temporary appliance network. Override the DNS server when
needed with `export SIMCXL_DNS_NAMESERVERS="<reachable DNS IP>"` before setup.
The guest script checks DNS first and stops if package-index downloads fail.
It also replaces the upstream disk's mixed Ubuntu release sources with the
official repositories matching `/etc/os-release`, preserving the original
configuration under `/opt/btp/config/apt-before-provision` in the working disk.
Provisioning failures are logged inside that disk at `/tmp/builder.log`;
`libguestfs-test-tool` only tests the appliance, not workload provisioning.

`prepare` performs a sparse extraction to `images/base.img`, makes a separate
working copy, then uses [virt-customize](https://libguestfs.org/virt-customize.1.html)
to install packages and build the guest utilities and workloads against the
guest's libc. It does not build gem5 or execute a workload. The base disk is
preserved. If extraction is interrupted, repeat the same `prepare` command:
setup preserves `base.img.part` as `base.img.part.interrupted-<timestamp>` and
restarts extraction using the verified downloaded archive. Extraction progress
is printed periodically; concurrent extraction attempts are rejected. After a
successful preparation, the preserved partial files can be deleted to reclaim
space. A failed preparation after extraction stays at `images/btp.preparing.img`.
Retry with `python3 guest/setup.py prepare --profile basic --jobs 2 --resume`:
this uploads the updated scripts and repeats provisioning in the existing working
disk, preserving installed packages and avoiding another large disk copy. Use the
same profile as the failed attempt. The resolver may be absent or a dangling
symlink; provisioning creates it and preserves an existing entry when available.
Concurrent preparation attempts are rejected. Never edit a disk that another
tool is currently using.
The provisioning tool inspects the root partition instead of assuming `/dev/sda1`.

The host needs network access and enough space for the compressed archive,
expanded base, and prepared disk. A sparse/reflink copy is attempted, but guest
package and model installation still consumes real disk space. The `doctor`
command reports currently available space and tools. Host image tools are
system packages; the simulated kernel, disk, sources, environments, and results
are stored inside this repository directory.

On a new checkout, stage workload sources before `prepare`:

```bash
python3 guest/setup.py sources
```

Or reuse the supplied source repositories without downloading them again:

```bash
python3 guest/setup.py sources \
  --study-root /home/mahaswin/Downloads/BTP_CXL_Study
```

This archives exact recorded Git revisions, preserving third-party license
files. It does not copy the native `.venv`, native executables, old results, or
local uncommitted changes in upstream repositories. Small user workload drivers
and the fixed prompt are already under `payload/src`, with provenance recorded.

## First CXL run

Build the current simulator yourself, then run the memory pilot:

```bash
scons --ignore-style build/X86/gem5.opt -j2
python3 guest/run.py --workload memory_pilot --cores 1
```

`--ignore-style` skips gem5's optional Git-hook installation prompt. The
`pre-commit` and `mypy` entries in `requirements.txt` are development tools;
installing them into system Python is not needed to resolve this build prompt.
If you want those tools for development, install them in a virtual environment.

The launcher selects KVM boot only if `/dev/kvm` is accessible, otherwise atomic
boot. Both switch to timing mode before the workload starts. Atomic boot can
be slow. `--boot-cpu kvm` requires working host KVM access; `--cpu o3` selects O3
for the measured workload. `--max-ticks N` imposes a total simulated-tick limit;
a run that reaches the limit before completion is marked failed, not successful.

The downloaded kernel uses the patched CXL guest memory path. The custom
`init=/opt/btp/boot.sh` mounts essential pseudo-filesystems, performs device
initialization, onlines discovered memory blocks, and reads the selected command
from m5. This bypasses benchmark autoruns embedded in the upstream disk. If CXL
NUMA node 1 is not present, the workload fails rather than falling back to DRAM.

The workload is launched using `numactl --membind=1 --cpunodebind=0`. The host
runner also checks that a complete `workload` phase exists and contains nonzero
CXL requests. Use `--node 0` only for an intentional simulated-DRAM control.

Output goes to a unique directory under `guest/results/`:

- `cxl-metrics.json`: the CXL metrics, including the `workload` interval report.
- `cxl-events.jsonl`: lifecycle trace consumed by the reporter.
- `workload.log`: application output copied out of the simulated guest.
- `workload-status.txt`: command, placement, threads, and guest return code.
- `numa.txt`: the guest NUMA topology.
- `guest-run-status.json`: whether the boot/switch/workload sequence completed.
- `guest-image-provenance.json`: base-image and source revision information.
- Standard gem5 configuration, stats, and serial-console files.

The guest working disk is read through gem5's existing copy-on-write disk object;
per-run application output is exported through `m5 writefile` to survive exit.

## Run the workload suite with one command

To prepare the `all` image and then run all eight supported workloads (including
the three basic workloads), use this after building gem5:

```bash
make workloads-full JOBS=2
```

Use the terminal with your `SUPERMIN_KERNEL` and `SUPERMIN_MODULES` exports.
This target downloads dependencies/models and builds guest workloads. It stages
the upgrade in `images/btp.all.preparing.img`; a failed preparation leaves the
basic image usable and rerunning the command retries the same staging image.
On success, the basic disk and receipt are preserved as `btp.basic.img` and
`btp.basic.img.json`, and the all image becomes `btp.img`. If the all image is
already prepared, provisioning is skipped. A provisioning error prevents the
suite from starting. The all-profile provision and workloads still need full
validation on this PC; this target automates that existing workflow.

If the builds completed and preparation failed during model downloads, retry
only that stage before running the suite:

```bash
make workloads-full JOBS=2 PREPARE_ARGS="--models-only"
```

This requires the existing `btp.all.preparing.img`, checks that the workload
executables exist, and skips apt, pip installation, CMake, and compilation.
It repairs the temporary appliance network, downloads remaining model files,
and finalizes the image. To finish preparation without starting any workloads,
use `python3 guest/setup.py ensure-all --models-only --jobs 2` instead.

After building gem5 and preparing the guest image:

```bash
make workloads
```

Equivalently, run `python3 guest/run_all.py`. The suite runs sequentially and
selects all supported workloads installed in the image. A `basic` image runs
`memory_pilot`, `stream`, and `pointer_chase`. An `all` image additionally runs
`ann`, `bert`, `kmeans`, `dlrm`, and `llama_cpp`. Unavailable workloads are
printed explicitly. GUPS is not runnable yet.

Each invocation creates `guest/results/suite-<timestamp>/`, with a separate
output directory and runner log per workload/repetition. Each successful run
has the same CXL reports as `run.py`; `summary.csv` and `summary.json` record
statuses, exit codes, and paths to the logs and metric files. Application output
and simulator diagnostics are in those files; the terminal shows suite progress.
The default stops at the first failure, leaving later entries as `not_run`.
The suite exits nonzero if any run fails, even with `--keep-going`.

```bash
make workloads-dry-run
make workloads ARGS="--cores 2 --repeat 3 --keep-going"
python3 guest/run_all.py --workloads stream pointer_chase
python3 guest/run_all.py -- --cpu o3 --max-ticks 1000000000000
make workloads-all
```

`--dry-run` validates prerequisites and prints commands without launching gem5
or creating results. `workloads-all` requires an image prepared with profile
`all` and fails early on a basic image. Neither target builds gem5 nor prepares
an image. Use `make build JOBS=2` when you explicitly want to build gem5.

## Smaller runs and runtime calibration

`--size smoke` preserves the full workload defaults and stages updated drivers
only in each simulation's copy-on-write disk overlay. No shared image is edited.
Small STREAM, pointer-chase, and ANN executables are compiled during fast boot,
before switching to timing mode. This can run alongside an existing suite:

```bash
make workloads-smoke
```

For up to 45 minutes of simulator execution per workload, with periodic stats
snapshots and no global suite timeout:

```bash
make workloads-trial
```

Workloads finishing sooner proceed immediately. At 45 minutes an unfinished
simulation receives a graceful interrupt, preserving its trace and final stats.
The reporter writes `cxl-metrics.partial.json` when possible; these trials are
labelled `trial_incomplete`, never successful benchmark measurements. Report
processing time is recorded separately and is additional to the sample interval.
The suite continues after trial cutoffs and other failures.

| Workload | Smoke settings |
|---|---|
| Memory pilot | 1 MiB, 8 passes |
| STREAM | 65,536 elements per array, 3 iterations |
| Pointer chase | 2 MiB, 1 sample, 10 ms sampling interval |
| ANN | 1,024 database vectors, 8 queries, 128 dimensions |
| BERT | Batch 1, sequence 8, no warmup, 1 iteration |
| K-means | 512 samples, 8 features, 4 clusters, 2 iterations |
| DLRM | Four 1,000-row embedding tables, dimension 16, 2 batches of 2 |
| Llama | Same 1B model, prompt `Hello`, 2 output tokens |

These reduce pilot memory by 8x, STREAM element-iterations by about 5,086x,
and ANN database size by about 195x. BERT/Llama still load the original model
weights, so input reduction does not eliminate their initialization cost.
Small working sets may fit in caches; smoke results validate the measurement
pipeline and must not be presented as equivalent to the original benchmarks.

Separate `guest/results/suite-smoke-<timestamp>/` folders contain `summary.csv`,
`calibration.json`, and per-run `workload-config.json` and `timing.json`. The
calibration summary reports whether all eight completed within six hours only
after all eight actually complete; incomplete samples leave that answer unknown.
Concurrent runs contend for host CPU/RAM and can change the measured wall time.

## Full workload profiles

`--profile basic` builds memory pilot, STREAM, and pointer chase. Use it to
validate boot, CXL placement, and metrics collection before expensive workloads.
STREAM retains 50,000,000 elements and 20 iterations; pointer chase retains
512 MiB, five samples, and one thread. The pilot uses 8 MiB for the first check.

`--profile all` additionally builds ANN and llama.cpp, installs guest Python
packages for BERT/DLRM/KMeans, and downloads the BERT and Q4_K_M Llama weights
before simulation. These preparation builds/downloads are substantial and run
only when you invoke the command. GUPS/HPCC source is staged, but its
RandomAccess-only build/run configuration remains to be added; it is deliberately
not exposed as a successful workload command.

To keep a basic image while creating the larger image:

```bash
mv guest/images/btp.img guest/images/btp-basic.img
mv guest/images/btp.img.json guest/images/btp-basic.img.json
python3 guest/setup.py prepare --profile all --jobs 2
```

Then select one workload at a time:

```bash
python3 guest/run.py --workload stream --cores 8
python3 guest/run.py --workload pointer_chase --cores 1
python3 guest/run.py --workload ann --cores 8
python3 guest/run.py --workload bert --cores 8
python3 guest/run.py --workload dlrm --cores 8
python3 guest/run.py --workload kmeans --cores 8
python3 guest/run.py --workload llama_cpp --cores 8
```

The upstream guest uses Python 3.6. Direct Python dependencies are pinned in
`payload/config/requirements-all.txt`, and the CPU-only PyTorch wheel is pinned
to 1.10.2. Its dependencies are installed from PyPI before fetching the wheel
from the PyTorch index, avoiding silent fallback to an older PyTorch version.
ONNX is omitted because the DLRM command does not request ONNX export. The
guest runs `pip check` and small import/API checks before compiling the larger
workloads. The model downloader uses the pinned Hub client's
[compatible download API](https://github.com/huggingface/huggingface_hub/blob/v0.4.0/src/huggingface_hub/file_download.py)
and resolves relative redirect locations against the response URL, fixing the
old client's `MissingSchema` failure on current model URLs. It stages BERT
files explicitly for offline execution. K-means uses sklearn
0.24's `full` spelling for the Lloyd algorithm.

Resolved Python packages are recorded in `/opt/btp/config/python-freeze.txt`; system packages
are recorded in `packages.txt`. These environments are not yet locked to the
original native environment, so do not claim identical dependency versions
across the two measurements. The C/C++ builds use conservative ISA settings
rather than host-specific `-march=native`. Llama uses `--no-mmap` for explicit
allocated model storage under the NUMA memory policy; that differs from the
supplied native launcher and is recorded in the executed command.

Models are available offline during simulation. Named `prefill`/`decode`
instrumentation inside the LLM is not added by this setup: the current launcher
marks the whole executable as `workload`. Existing application output is retained;
no native perf counters are duplicated by the CXL collector.

Bandwidth reporting capacities default to unspecified. Supply measured/configured
payload limits with `--read-bandwidth BPS --write-bandwidth BPS`; these are metrics
denominators and do not add a transport throttle. `--cxl-version` is a run label
and defaults to `unspecified`, rather than claiming an unsupported version.
See [the metric definitions](../doc/cxl-metrics.md) for model boundaries.

## Short checks

```bash
python3 -m unittest discover -s tests/cxl -p 'test_*.py' -v
python3 -m py_compile guest/setup.py guest/run.py guest/simulate.py
bash -n guest/payload/provision.sh guest/payload/boot.sh guest/payload/run-workload.sh
```

These checks do not establish guest boot or workload correctness. A successful
image preparation and memory-pilot simulation are the next integration gates.
