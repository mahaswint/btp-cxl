"""Prespecified GAP graph sweep, with paper-size windows and labeled sensitivity."""
import argparse
import csv
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--representative", action="store_true", help="Use highest-weight published regions")
args = parser.parse_args()
output = root / "results" / ("graph_representative" if args.representative else "graph")
output.mkdir(exist_ok=True)
exe = root / ("dynamic_profiler.exe" if sys.platform == "win32" else "dynamic_profiler")
traces = ["bc_bc.kron-2608B.champsimtrace.bin", "bc_bc.twitter-309B.champsimtrace.bin",
          "tc_tc.twitter-34B.champsimtrace.bin"]
if args.representative:
    traces = ["bc_bc.kron-5154B.champsimtrace.bin", "bc_bc.twitter-876B.champsimtrace.bin",
              "tc_tc.twitter-4460B.champsimtrace.bin"]
rows = []
for trace in traces:
    name = trace.replace(".champsimtrace.bin", "")
    for window, capacities in ((20_000_000, (64, 256, 1024)), (1_000_000, (256,))):
        for capacity in capacities:
            prefix = output / f"{name}_window{window}_cap{capacity}"
            subprocess.run([str(exe), "--trace", str(root / "traces" / "graph" / trace),
                "--out", str(prefix), "--instructions", "12000000", "--warmup", "200000",
                "--window-ns", str(window), "--capacity", str(capacity), "--reserve", "0",
                "--dram-ns", "80", "--cxl-ns", "250", "--batch", "64",
                "--migration-gbps", "10", "--move-overhead-ns", "1000"],
                check=True, capture_output=True, text=True)
            with Path(str(prefix) + ".csv").open() as f:
                results = {r["policy"]: r for r in csv.DictReader(f)}
            f, p = results["frequency"], results["pac"]
            with Path(str(prefix) + "_pac_windows.csv").open() as handle:
                windows = list(csv.DictReader(handle))
            mlps = [float(w["cxl_mlp"]) for w in windows if int(w["cxl_misses"]) > 0]
            rows.append({"trace": name, "window_ns": window, "capacity_pages": capacity,
                "cxl_ns": results["cxl"]["runtime_ns"], "dram_ns": results["dram"]["runtime_ns"],
                "frequency_ns": f["runtime_ns"], "pac_ns": p["runtime_ns"],
                "reduction_percent": 100 * (float(f["runtime_ns"]) - float(p["runtime_ns"])) / float(f["runtime_ns"]),
                "frequency_promotions": f["promotions"], "pac_promotions": p["promotions"],
                "frequency_migration_ns": f["migration_ns"], "pac_migration_ns": p["migration_ns"],
                "pac_decisions": p["decisions"], "pac_min_mlp": min(mlps) if mlps else 0,
                "pac_max_mlp": max(mlps) if mlps else 0})
            print(f"Finished {name}: window={window}, capacity={capacity}, PAC reduction={rows[-1]['reduction_percent']:.3f}%", flush=True)
with (output / "campaign.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
