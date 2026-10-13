"""Controlled length/window sweep; retain every outcome and validate accounting."""
import csv
import math
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
output = root / "results" / "graph_windows"
output.mkdir(exist_ok=True)
exe = root / ("dynamic_profiler.exe" if sys.platform == "win32" else "dynamic_profiler")
trace = root / "traces" / "graph" / "bc_bc.twitter-876B.champsimtrace.bin"
rows = []
for instructions in (12_000_000, 48_000_000):
    for window in (20_000_000, 5_000_000, 1_000_000, 200_000):
        prefix = output / f"bc_twitter876_n{instructions}_window{window}"
        # Reuse exactly matching earlier comparisons; do not mix trace regions.
        if instructions == 12_000_000 and window in (20_000_000, 1_000_000):
            prefix = root / "results" / "graph_representative" / f"bc_bc.twitter-876B_window{window}_cap256"
        if not Path(str(prefix) + ".csv").exists():
            completed = subprocess.run([str(exe), "--trace", str(trace), "--out", str(prefix),
                "--instructions", str(instructions), "--warmup", "200000", "--window-ns", str(window),
                "--capacity", "256", "--reserve", "0", "--dram-ns", "80", "--cxl-ns", "250",
                "--batch", "64", "--migration-gbps", "10", "--move-overhead-ns", "1000"],
                capture_output=True, text=True)
            if completed.returncode:
                Path(str(prefix) + ".csv").unlink(missing_ok=True)
                raise RuntimeError(completed.stderr or completed.stdout)
        config = dict(line.split("=", 1) for line in Path(str(prefix) + "_config.txt").read_text().splitlines())
        assert int(config["instructions"]) == instructions and int(config["window_ns"]) == window
        assert int(config["capacity"]) == 256 and int(config["warmup"]) == 200000
        with Path(str(prefix) + ".csv").open() as handle:
            policies = {r["policy"]: r for r in csv.DictReader(handle)}
        assert set(policies) == {"cxl", "dram", "frequency", "pac"}
        loads = int(policies["cxl"]["cxl_loads"])
        for name, p in policies.items():
            assert int(p["dram_loads"]) + int(p["cxl_loads"]) == loads
            if name not in ("frequency", "pac"):
                continue
            with Path(str(prefix) + f"_{name}_windows.csv").open() as handle:
                windows = list(csv.DictReader(handle))
            with Path(str(prefix) + f"_{name}_moves.csv").open() as handle:
                moves = list(csv.DictReader(handle))
            assert len(windows) == int(p["decisions"])
            assert sum(m["direction"] == "CXL_to_DRAM" for m in moves) == int(p["promotions"])
            assert sum(m["direction"] == "DRAM_to_CXL" for m in moves) == int(p["demotions"])
            assert math.isclose(float(p["migration_ns"]), len(moves) * 1409.6, abs_tol=1e-5)
            previous = 0
            for w in windows:
                assert int(w["dram_pages"]) <= 256
                assert float(w["sample_ns"]) > previous
                assert float(w["resume_ns"]) <= float(p["runtime_ns"])
                previous = float(w["resume_ns"])
        frequency, pac = policies["frequency"], policies["pac"]
        row = {"instructions": instructions, "window_ms": window / 1e6,
            "reduction_percent": 100 * (1 - float(pac["runtime_ns"]) / float(frequency["runtime_ns"])),
            "source_prefix": str(prefix.relative_to(root))}
        for name, p in policies.items():
            for field in ("runtime_ns", "migration_ns", "drain_ns", "decisions", "promotions", "dram_loads", "cxl_loads"):
                row[f"{name}_{field}"] = p[field]
        rows.append(row)
        # Save progress after each validated comparison; failed runs aren't cached.
        with (output / "campaign.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Validated {instructions/1e6:g}M, {window/1e6:g} ms: PAC reduction {row['reduction_percent']:+.3f}%", flush=True)

lines = ["# Continuous length and recalculation-window sweep", "",
    "Same real bc-twitter region 876 prefix, 200k warmup, no looping or concatenation.",
    "12M versus 48M runtime instructions; settings selected before measuring outcomes.",
    "256 DRAM pages, 80/250 ns DRAM/CXL, 16 memory slots, 1 MiB cache, 64-page batches,",
    "no eager reserve, 10 GB/s copying plus 1000 ns per moved page.",
    "All windows except 20 ms are sensitivity experiments. Modeled runtime, not hardware measurements.", "",
    "Positive reduction means PAC is faster than dynamic frequency.", "",
    "| Instructions | Window ms | Frequency ms | PAC ms | Reduction | Frequency/PAC updates | Frequency/PAC copy ms | All-CXL ms | All-DRAM ms |",
    "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
for r in rows:
    lines.append(f"| {int(r['instructions'])/1e6:g}M | {r['window_ms']:g} | "
        f"{float(r['frequency_runtime_ns'])/1e6:.3f} | {float(r['pac_runtime_ns'])/1e6:.3f} | "
        f"{r['reduction_percent']:+.3f}% | {r['frequency_decisions']}/{r['pac_decisions']} | "
        f"{float(r['frequency_migration_ns'])/1e6:.3f}/{float(r['pac_migration_ns'])/1e6:.3f} | "
        f"{float(r['cxl_runtime_ns'])/1e6:.3f} | {float(r['dram_runtime_ns'])/1e6:.3f} |")
lines += ["", "## Runtime-difference accounting", "",
    "Positive values favor PAC. Residual is total savings minus copy and drain savings;",
    "it captures the remaining execution difference, not a direct hardware stall measurement.", "",
    "| Instructions | Window ms | Total saved ms | Copy saved ms | Drain saved ms | Residual saved ms |",
    "| ---: | ---: | ---: | ---: | ---: | ---: |"]
for r in rows:
    total = float(r['frequency_runtime_ns']) - float(r['pac_runtime_ns'])
    copy = float(r['frequency_migration_ns']) - float(r['pac_migration_ns'])
    drain = float(r['frequency_drain_ns']) - float(r['pac_drain_ns'])
    lines.append(f"| {int(r['instructions'])/1e6:g}M | {r['window_ms']:g} | "
        f"{total/1e6:+.4f} | {copy/1e6:+.4f} | {drain/1e6:+.4f} | {(total-copy-drain)/1e6:+.4f} |")
lines += ["", "Each case passed load-count conservation, capacity, decision-time, and migration accounting checks.",
    "Full counts, drain times, provenance, and every outcome are in [campaign.csv](campaign.csv).",
    "Sampling cost is zero in this analytical model; migration is synchronous and charged.",
    "Faster than frequency need not mean faster than all-CXL. Longer execution within",
    "one trace region still does not reproduce a full multithreaded application's phase mix."]
(output / "REPORT.md").write_text("\n".join(lines) + "\n")
