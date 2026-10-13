"""Reproducible held-out capacity/latency/parallelism sweep."""
import csv
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
exe = root / ("trace_profiler.exe" if sys.platform == "win32" else "trace_profiler")
records = []
for trace in sorted((root / "traces").glob("*.bin")):
    for slow in (160, 250, 400):
        for mlp in (1, 8, 16):
            name = trace.name.replace(".champsimtrace.bin", "")
            prefix = root / "results" / f"{name}_slow{slow}_mlp{mlp}"
            subprocess.run([str(exe), "--trace", str(trace), "--out", str(prefix),
                "--slow-ns", str(slow), "--mlp", str(mlp),
                "--criticality", "slack",
                "--capacities", "0,16,64,256,1024"], check=True, capture_output=True, text=True)
            with Path(str(prefix) + ".csv").open() as f:
                for row in csv.DictReader(f):
                    records.append({"trace": name, "slow_ns": slow, "mlp": mlp, **row})
            print(f"Finished {name}: slow={slow} ns, MLP={mlp}", flush=True)
if not records:
    raise SystemExit("No traces found; run fetch_traces.py first")
with (root / "results" / "campaign.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
