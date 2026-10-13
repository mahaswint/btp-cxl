"""Apply a sourced approximate tier profile, keeping cycle coefficients distinct."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--trace", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument("--instructions", type=int, default=1_000_000)
parser.add_argument("--window-ns", type=float, default=20_000_000)
parser.add_argument("--capacity", type=int, default=256)
parser.add_argument("--score-clock-ghz", type=float, help="Explicit cycles-to-ns assumption for PAC k, not execution clock")
args = parser.parse_args()
if args.score_clock_ghz is not None and (not math.isfinite(args.score_clock_ghz) or args.score_clock_ghz <= 0):
    parser.error("--score-clock-ghz must be finite and positive")
profile = json.loads((root / "calibration/pact/reference_profile.json").read_text())
tiers = {t["tier"]:t for t in profile["tiers"]}
args.out.parent.mkdir(parents=True, exist_ok=True)
exe = root / ("dynamic_profiler.exe" if sys.platform == "win32" else "dynamic_profiler")
command = [str(exe), "--trace", str(args.trace.resolve()), "--out", str(args.out.resolve()),
    "--instructions", str(args.instructions), "--window-ns", str(args.window_ns), "--capacity", str(args.capacity),
    "--dram-ns", str(tiers["local_dram"]["nominal_latency_ns"]),
    "--cxl-ns", str(tiers["cxl_emulated"]["nominal_latency_ns"])]
if args.score_clock_ghz is not None:
    command += ["--pac-k-dram-ns", str(tiers["local_dram"]["fitted_k_cycles"]/args.score_clock_ghz),
        "--pac-k-cxl-ns", str(tiers["cxl_emulated"]["fitted_k_cycles"]/args.score_clock_ghz)]
Path(str(args.out)+"_profile.json").write_text(json.dumps({"profile":profile,
    "score_clock_ghz_assumption":args.score_clock_ghz,
    "pac_k_mode":"fitted cycles converted using declared clock" if args.score_clock_ghz else "nominal tier latency fallback",
    "exact_latency_replay":False, "command":command}, indent=2)+"\n")
subprocess.run(command, check=True)
