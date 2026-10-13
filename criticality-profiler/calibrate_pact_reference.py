"""Fit PACT's public hardware-counter reference; never infer request timestamps."""
import csv
import hashlib
import json
import math
from pathlib import Path
import re

root = Path(__file__).resolve().parent
source = root / "calibration" / "pact"
manifest = json.loads((source / "manifest.json").read_text())
for entry in manifest["files"]:
    assert hashlib.sha256((source / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
with (source / "modeling/skx/dat/r-l3_stall_skx.csv").open() as handle:
    rows = list(csv.DictReader(handle))
assert len({r["workload"] for r in rows}) == len(rows)

def correlation(x, y):
    ax, ay = sum(x)/len(x), sum(y)/len(y)
    return sum((a-ax)*(b-ay) for a,b in zip(x,y)) / math.sqrt(
        sum((a-ax)**2 for a in x) * sum((b-ay)**2 for b in y))

tiers = []
for tier, name, nominal in ((1, "local_dram", 90), (2, "remote_numa", 140), (3, "cxl_emulated", 190)):
    x, y, misses = [], [], []
    for r in rows:
        miss, mlp = float(r[f"l3_miss_{tier}"]), float(r[f"demand_l2_mlp_{tier}"])
        feature, stall = float(r[f"(l3_miss/mlp)_{tier}"]), float(r[f"l3_stall_{tier}"])
        assert all(math.isfinite(v) and v > 0 for v in (miss, mlp, feature, stall))
        assert math.isclose(feature, miss/mlp, rel_tol=1e-8)
        x.append(feature)
        y.append(stall)
        misses.append(miss)
    xx, xy = sum(v*v for v in x), sum(a*b for a,b in zip(x,y))
    k = xy/xx  # Through-origin least squares, matching corr.plot's fit.
    loo = [((xy-a*b)/(xx-a*a))*a for a,b in zip(x,y)]
    tiers.append({"tier": name, "nominal_latency_ns": nominal,
        "latency_evidence": "approximate tier label in authors' modeling documentation",
        "fitted_k_cycles": k, "samples": len(rows),
        "miss_stall_correlation": correlation(misses, y),
        "miss_over_mlp_stall_correlation": correlation(x, y),
        "leave_one_out_rmse_cycles": math.sqrt(sum((p-b)**2 for p,b in zip(loo,y))/len(y)),
        "leave_one_out_mean_absolute_percent_error": 100*sum(abs(p-b)/b for p,b in zip(loo,y))/len(y)})

pmu = (source / "src/pmu-platform.c").read_text()
for tier, key in ((tiers[0], "dram"), (tiers[2], "cxl")):
    runtime_k = int(re.search(r"\.k_constant_"+key+r"\s*=\s*(\d+)", pmu).group(1))
    assert round(tier["fitted_k_cycles"]) == runtime_k

profile = {"name": "pact_skx_counter_reference", "source_commit": manifest["commit"],
    "reference_workloads": len(rows), "kind": "hardware counter calibration with NUMA-based CXL emulation",
    "exact_request_latencies": False, "tiers": tiers,
    "score_units": "cycles; conversion to ns requires a declared clock frequency",
    "unsupported": ["per-access timestamps", "page-address timing correspondence", "latency distribution",
        "physical CXL device service-time calibration", "migration and sampling overhead calibration"]}
(source / "reference_profile.json").write_text(json.dumps(profile, indent=2)+"\n")
melody = root / "calibration/melody"
melody_manifest = json.loads((melody / "manifest.json").read_text())
for entry in melody_manifest["files"]:
    assert hashlib.sha256((melody / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
with (melody / "data/emr/emr-cxl-a.csv").open() as handle:
    real_rows = list(csv.DictReader(handle))
assert all(math.isfinite(float(r["slowdown"])) and float(r["slowdown"]) > 0 for r in real_rows)
lines = ["# PACT hardware-counter calibration audit", "",
    f"Source pinned to PACT commit `{manifest['commit']}`. Actual CSV has {len(rows)} workloads,",
    "although its README describes 95. Hashes and miss/MLP identities were verified.", "",
    "Fit: measured LLC stall cycles = k × (LLC misses / measured MLP), through the origin.",
    "Leave-one-out error evaluates each workload with its own row excluded from fitting.", "",
    "| Tier | Approximate tier label ns | Fitted k cycles | Miss correlation | Miss/MLP correlation | LOO mean absolute error |",
    "| --- | ---: | ---: | ---: | ---: | ---: |"]
for t in tiers:
    lines.append(f"| {t['tier']} | {t['nominal_latency_ns']} | {t['fitted_k_cycles']:.3f} | "
        f"{t['miss_stall_correlation']:.4f} | {t['miss_over_mlp_stall_correlation']:.4f} | "
        f"{t['leave_one_out_mean_absolute_percent_error']:.2f}% |")
lines += ["", "The fitted local/slow values reproduce the artifact's rounded 238/771 constants.",
    "These coefficients describe effective stalls. They are not memory-service latency in nanoseconds.",
    "The CSV's offcore_load_latency fields are retained as source data but not used as nanoseconds:",
    "their measurement provenance/clock conversion is not established by the checked-in collector,",
    "which writes zero placeholders for these fields in newly collected rows.", "",
    "## Real-CXL artifact checked", "",
    f"Melody's EMR CXL-A CSV contains {len(real_rows)} whole-workload runtime ratios versus local memory.",
    "MIO documentation describes averaged pointer-chase latency samples, but the inspected repository",
    "does not include the corresponding raw measurement logs. Slowdown ratios cannot identify",
    "per-access latency, queue delay, or page-address timing. Neither artifact supplies a timed",
    "instruction/request trace interchangeable with our ChampSim inputs.", "",
    "## Applying this evidence", "",
    "Use run_pact_reference.py for an explicitly approximate 90/190 ns service-latency scenario.",
    "It retains the original baseline defaults elsewhere. Optionally declare --score-clock-ghz",
    "to convert the fitted cycle coefficients for score scaling; that clock is an explicit",
    "conversion assumption, not recovered measurement metadata. Runtime core timing is unchanged.",
    "Because only CXL misses add PAC scores, changing a fixed positive CXL k alone generally",
    "rescales the scores without adding page-level information or changing rankings.", "",
    "Exact observed request latency would require matching issue/completion timestamps or",
    "documented per-load latency samples with units and tier attribution. Moving pages changes",
    "queuing and overlap, so even a fixed replay of observed latencies is not exact for new placements.", "",
    "Sources: [PACT modeling](https://github.com/MoatLab/PACT/tree/main/modeling),",
    "[PACT PMU coefficients](https://github.com/MoatLab/PACT/blob/main/src/pmu-platform.c),",
    "[Melody](https://github.com/MoatLab/Melody)."]
lines += ["", "## Reproduce", "", "```powershell",
    "python calibrate_pact_reference.py",
    "python run_pact_reference.py --trace traces/graph/bc_bc.twitter-876B.champsimtrace.bin --out results/pact_reference/bc_twitter876_1m_200us --instructions 1000000 --window-ns 200000 --score-clock-ghz 3",
    "```", "", "The explicit 3 GHz conversion matches the profiler's default core-tick assumption;",
    "it is not evidence that the measurement server ran at 3 GHz. This 1M replay is a",
    "functional check of the profile path, not a measured hardware performance result.",
    "Omit --score-clock-ghz to use nominal latency as k, preserving the previous scoring convention.",
    "Both variants are estimates. The calibration-only coefficients remain in cycles in reference_profile.json."]
(source / "REPORT.md").write_text("\n".join(lines)+"\n")
print(json.dumps({"workloads":len(rows), "tiers":tiers}, indent=2))
