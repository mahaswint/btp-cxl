"""Run the documented dynamic policy examples with fixed, reviewable settings."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
out = root / "results" / "dynamic"
out.mkdir(exist_ok=True)
exe = root / ("dynamic_profiler.exe" if sys.platform == "win32" else "dynamic_profiler")
cases = [
    ("pilot", "605.mcf_s-1554B.champsimtrace.bin", 1_000_000, 200_000, 64, 0),
    ("mcf_long20ms", "long/605.mcf_s-1554B.champsimtrace.bin", 12_000_000, 20_000_000, 256, 0),
    ("mcf_long1ms_reserve8", "long/605.mcf_s-1554B.champsimtrace.bin", 12_000_000, 1_000_000, 256, 8),
    ("lbm_short200us", "619.lbm_s-2676B.champsimtrace.bin", 1_000_000, 200_000, 64, 0),
    ("xalancbmk_short200us", "623.xalancbmk_s-165B.champsimtrace.bin", 1_000_000, 200_000, 64, 0),
]
for name, trace, count, window, capacity, reserve in cases:
    subprocess.run([str(exe), "--trace", str(root / "traces" / trace), "--out", str(out / name),
        "--instructions", str(count), "--window-ns", str(window), "--capacity", str(capacity),
        "--reserve", str(reserve)], check=True)
