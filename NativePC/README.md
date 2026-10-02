# Native PC experiments

Native-machine workload sources and recorded experiments imported from the existing `BTP_CXL_Study` working directory. The original study directory was left unchanged.

## Contents

- `workloads/`: benchmark sources and workload-specific launchers, including locally modified DLRM phase-timing instrumentation.
- `scripts/`: profiling, campaign, processing and plotting helpers. Their study-root paths are relative to this folder rather than the original home-directory location.
- `raw_data/`: original native measurements, including 54 run directories containing `metadata.txt`, campaign logs and validation output. These are recorded attempts, not a claim that every run succeeded.
- `processed_data/` and `visualizations/`: existing derived results and plots.
- `config/` and `system_info/`: recorded settings, environment details and source revisions.
- `run_kaggle_pt/`: existing study material, retained separately from local-PC measurements.
- `experiments/ocean-comparison-2026-09-29/`: pointer-chase source and the native baseline/repeat logs from the OCEAN validation experiment.

Historical logs and reports retain their original paths and timestamps. They have not been regenerated during this import.

## Running again

This is a source-and-results archive, not a prebuilt environment. Recreate `.venv`, install the workload dependencies, rebuild the required native executables and obtain model weights before launching a campaign. Use the recorded environment information in `system_info/` and each upstream project's build documentation. Check the CPU affinity and workload sizes in the launch scripts for the target PC.

From this directory, the campaign entry point is `bash scripts/run_full_native_campaign.sh`. It runs substantial workloads and may need performance-counter access. Some campaign status files and derived reports are overwritten on another run; preserve any results you need before rerunning.

The small pointer-chase comparison is independent of the ML environment; see its [experiment notes](experiments/ocean-comparison-2026-09-29/README.md).

## Imported upstream sources

Upstream source snapshots are included without their nested Git histories. An import commit records this workspace change; it does not claim authorship of third-party sources. Their existing licenses and source credits are retained.

| Directory under `workloads/` | Upstream | Imported revision |
| --- | --- | --- |
| `STREAM` | https://github.com/jeffhammond/STREAM | `6703f7504a38a8da96b353cadafa64d3c2d7a2d3` |
| `ann/faiss` | https://github.com/facebookresearch/faiss | `af9eeffcf70d7795107c2b0511bdba507ac45339` |
| `embedding_recommendation/dlrm` | https://github.com/facebookresearch/dlrm | `9bc1bc3602aea22afad3206910cec50f2dbe7364` |
| `gups/hpcc` | https://github.com/j-r-jones/hpcc | `9213b982f84ac4ad7d8418cdd65d7259d6f71c42` |
| `llama_cpp/llama.cpp` | https://github.com/ggml-org/llama.cpp | `0eadefebd3f8f92a86d634a0e5b8fffc9dc792c0` |
| `pointer_chase/multichase` | https://github.com/google/multichase | `4986aaf671b49f52ac1b451717e2cc693dcb3383` |

Local environments, build directories, compiled workload executables/libraries, GGUF files (including upstream GGUF test assets), and nested repository metadata are omitted. Rebuild outputs or restore required upstream test assets before running those upstream test suites.
