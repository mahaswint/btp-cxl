#!/usr/bin/env python3
"""Run pinned DLRM with initialization before the gem5 detailed-CPU ROI."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time


DLRM_ENTRY = Path(
    os.environ.get(
        "SIMCXL_DLRM_ENTRY", "/opt/btp/upstreams/dlrm/dlrm_s_pytorch.py"
    )
)
M5 = os.environ.get("SIMCXL_M5", "/opt/btp/bin/m5")
PHASE = os.environ.get("SIMCXL_PHASE", "/opt/btp/bin/phase")
STATUS = Path(os.environ.get("SIMCXL_ROI_STATUS", "/tmp/simcxl-roi-status.txt"))
WORKLOAD_LOG = Path(os.environ.get("SIMCXL_WORKLOAD_LOG", "/tmp/workload.log"))
WORKLOAD_STATUS = Path(
    os.environ.get("SIMCXL_WORKLOAD_STATUS", "/tmp/workload-status.txt")
)
EXIT_AT_ROI_END = os.environ.get("SIMCXL_EXIT_AT_ROI_END", "1") != "0"


def checked(command):
    subprocess.run(command, check=True)


def load_dlrm():
    if not DLRM_ENTRY.is_file():
        raise FileNotFoundError("DLRM entry point is missing: {}".format(DLRM_ENTRY))
    sys.path.insert(0, str(DLRM_ENTRY.parent))
    spec = importlib.util.spec_from_file_location("simcxl_pinned_dlrm", DLRM_ENTRY)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load DLRM entry point: {}".format(DLRM_ENTRY))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    process_start = time.perf_counter()
    dlrm = load_dlrm()
    original_inference = dlrm.inference
    calls = {"count": 0}

    def measured_inference(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] != 1:
            raise RuntimeError("DLRM ROI wrapper expected exactly one inference call")

        init_seconds = time.perf_counter() - process_start
        STATUS.write_text(
            "roi_switch_requested=1\n"
            "roi_init_seconds={:.6f}\n"
            "roi_cache_state=cold_at_switch\n".format(init_seconds)
        )
        print("DLRM_PHASE init_seconds={:.6f}".format(init_seconds), flush=True)
        print("=== DLRM ROI SWITCH REQUEST ===", flush=True)

        # gem5 handles this first normal exit by switching the processor and
        # resetting statistics. This subprocess resumes on the detailed CPU.
        checked([M5, "--addr", "exit"])
        print("=== DLRM ROI START (TIMING CPU) ===", flush=True)
        checked([PHASE, "begin", "workload"])
        roi_start = time.perf_counter()
        try:
            result = original_inference(*args, **kwargs)
        except BaseException:
            roi_seconds = time.perf_counter() - roi_start
            checked([PHASE, "end", "workload"])
            with STATUS.open("a") as status:
                status.write("roi_completed=0\n")
                status.write("roi_seconds={:.6f}\n".format(roi_seconds))
            raise

        roi_seconds = time.perf_counter() - roi_start
        checked([PHASE, "end", "workload"])
        with STATUS.open("a") as status:
            status.write("roi_completed=1\n")
            status.write("roi_seconds={:.6f}\n".format(roi_seconds))
        print("=== DLRM ROI END ===", flush=True)
        print(
            "DLRM_PHASE workload_seconds={:.6f}".format(roi_seconds),
            flush=True,
        )

        if EXIT_AT_ROI_END:
            if WORKLOAD_STATUS.is_file():
                with WORKLOAD_STATUS.open("a") as workload_status:
                    workload_status.write(STATUS.read_text())
                    workload_status.write("exit_code=0\n")
            checked([M5, "--addr", "writefile", str(STATUS), "roi-status.txt"])
            if WORKLOAD_STATUS.is_file():
                checked(
                    [
                        M5,
                        "--addr",
                        "writefile",
                        str(WORKLOAD_STATUS),
                        "workload-status.txt",
                    ]
                )
            if WORKLOAD_LOG.is_file():
                checked(
                    [M5, "--addr", "writefile", str(WORKLOAD_LOG), "workload.log"]
                )
            checked([M5, "--addr", "exit"])
            raise RuntimeError("gem5 final ROI exit unexpectedly returned")

        return result

    dlrm.inference = measured_inference
    dlrm.run()
    if calls["count"] != 1:
        raise RuntimeError(
            "DLRM finished without entering inference; CPU switch was not requested"
        )


if __name__ == "__main__":
    main()
