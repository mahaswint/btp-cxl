"""PACT-inspired scoring sweep; preserves the original slack campaign."""
import csv
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
exe = root / ("trace_profiler.exe" if sys.platform == "win32" else "trace_profiler")
output = root / "results" / "pac"
output.mkdir(exist_ok=True)
records = []
for trace in sorted((root / "traces").glob("*.bin")):
    name = trace.name.replace(".champsimtrace.bin", "")
    for window in (20_000, 200_000, 20_000_000):
        for slow in (160, 250, 400):
            for mlp in (1, 8, 16):
                prefix = output / f"{name}_window{window}_slow{slow}_mlp{mlp}"
                subprocess.run([str(exe), "--trace", str(trace), "--out", str(prefix),
                    "--criticality", "pac", "--pac-window-ns", str(window),
                    "--slow-ns", str(slow), "--mlp", str(mlp),
                    "--capacities", "0,16,64,256,1024"], check=True, capture_output=True, text=True)
                with Path(str(prefix) + ".csv").open() as f:
                    for row in csv.DictReader(f):
                        records.append({"trace": name, "window_ns": window,
                            "slow_ns": slow, "mlp": mlp, **row})
        print(f"Finished {name}: PAC window={window} ns", flush=True)
if not records:
    raise SystemExit("No traces found; run fetch_traces.py first")
with (output / "campaign.csv").open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(records[0]))
    writer.writeheader()
    writer.writerows(records)
