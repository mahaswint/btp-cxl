"""Re-use the full BC-kron compact cache; retain every fixed policy comparison."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results/paper_aligned"
CACHE = ROOT / "traces/graph/kron_full.cpt"
EXE = ROOT / ("compact_profiler.exe" if sys.platform == "win32" else "compact_profiler")
PROFILES = ("legacy", "paper-all-events", "paper-sampled")


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + 3600
    measurements = []
    def status(stage, **extra):
        (OUT / "status.json").write_text(json.dumps({"stage": stage,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": time.monotonic() - started, **extra}, indent=2) + "\n")
    try:
        status("validating_cached_input")
        metadata = json.loads((ROOT / "results/compact/cache_metadata.json").read_text())
        with CACHE.open("rb") as handle:
            cache_hash = hashlib.file_digest(handle, "sha256").hexdigest()
        if cache_hash != metadata["cache_sha256"]:
            raise RuntimeError("Cached graph differs from recorded full-trace preprocessing")
        provenance = {"cache_sha256": cache_hash, "cache_bytes": CACHE.stat().st_size,
            "raw_trace_identity": metadata["identity"],
            "replay_executable_sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
            "profiles_chosen_before_results": PROFILES,
            "note": "Replay-only policy changes use the previously validated graph. No trace concatenation, repetition or latency rescaling."}
        (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        baseline_loads = None
        for profile in PROFILES:
            budget = None
            for comparison in ("natural", "matched"):
                status("comparing", profile=profile, comparison=comparison)
                prefix = OUT / (profile.replace("-", "_") + "_" + comparison)
                args = [str(EXE), "--cache", str(CACHE), "--out", str(prefix),
                    "--policy-profile", profile, "--window-ns", "20000000"]
                if comparison == "matched":
                    args += ["--promotion-budget", str(budget)]
                begin = time.monotonic()
                with prefix.with_suffix(".log").open("w") as handle:
                    subprocess.run(args, check=True, stdout=handle, stderr=subprocess.STDOUT,
                        timeout=max(.01, deadline-time.monotonic()))
                rows = {r["policy"]: r for r in read_csv(prefix.with_suffix(".csv"))}
                config = dict(line.split("=", 1) for line in Path(str(prefix)+"_config.txt").read_text().splitlines())
                assert int(config["instructions"]) == 999800000
                assert int(config["capacity"]) == math.ceil(int(config["working_pages"])/2)
                loads = int(rows["cxl"]["cxl_loads"])
                if baseline_loads is None: baseline_loads = loads
                assert loads == baseline_loads
                for policy, r in rows.items():
                    assert math.isfinite(float(r["runtime_ns"])) and float(r["runtime_ns"]) > 0
                    assert int(r["dram_loads"])+int(r["cxl_loads"]) == loads
                    if policy not in ("frequency", "pac"): continue
                    moves = read_csv(Path(str(prefix)+f"_{policy}_moves.csv"))
                    windows = read_csv(Path(str(prefix)+f"_{policy}_windows.csv"))
                    assert len(windows) == int(r["decisions"])
                    assert sum(m["direction"]=="CXL_to_DRAM" for m in moves) == int(r["promotions"])
                    assert sum(m["direction"]=="DRAM_to_CXL" for m in moves) == int(r["demotions"])
                    assert math.isclose(len(moves)*1409.6, float(r["migration_ns"]), abs_tol=1e-4)
                    previous = -1
                    for w in windows:
                        assert float(w["sample_ns"]) > previous
                        assert float(w["resume_ns"]) <= float(r["runtime_ns"])
                        assert int(w["dram_pages"]) <= int(config["capacity"])
                        assert int(w["cxl_page_samples"]) <= int(w["cxl_misses"])
                        previous = float(w["resume_ns"])
                    if comparison == "matched": assert int(r["promotions"]) == budget
                f, p = rows["frequency"], rows["pac"]
                if comparison == "natural": budget = min(int(f["promotions"]), int(p["promotions"]))
                else: assert f["demotions"] == p["demotions"]
                mlp = [float(w["cxl_mlp"]) for w in read_csv(Path(str(prefix)+"_pac_windows.csv")) if int(w["cxl_misses"])]
                measurements.append({"profile": profile, "comparison": comparison,
                    "rows": rows, "config": config, "prefix": prefix.name,
                    "pac_nonempty_cxl_windows": len(mlp), "pac_mlp_min": min(mlp) if mlp else None,
                    "pac_mlp_max": max(mlp) if mlp else None,
                    "runtime_reduction_percent": 100*(1-float(p["runtime_ns"])/float(f["runtime_ns"])),
                    "wall_seconds": time.monotonic()-begin})
                (OUT / "measurements.json").write_text(json.dumps(measurements, indent=2)+"\n")
        lines = ["# Paper-aligned policy comparison on the full available BC-kron region", "",
            "All six fixed comparisons use the same 999,800,000 measured instructions, 525,613 working-set pages, "
            "262,807 DRAM pages, and 20 ms execution windows. The source is one complete public representative "
            "trace member, not the full multithreaded application. Cache and load-domain checks passed.", "",
            "| Profile | Migration control | Frequency (ms) | PAC (ms) | Runtime reduction | Promotions F/P | Updates F/P |", "|---|---|---:|---:|---:|---:|---:|"]
        for m in measurements:
            f,p = m["rows"]["frequency"],m["rows"]["pac"]
            lines.append(f'| {m["profile"]} | {m["comparison"]} | {float(f["runtime_ns"])/1e6:.6f} | '
                f'{float(p["runtime_ns"])/1e6:.6f} | {m["runtime_reduction_percent"]:+.6f}% | '
                f'{f["promotions"]}/{p["promotions"]} | {f["decisions"]}/{p["decisions"]} |')
        lines += ["", "Positive reduction means PAC has a shorter modeled runtime. The matched control uses the smaller "
            "natural promotion count as a cap and verifies that both policies actually reach it, with equal demotions. "
            "Migration timing and page choices can still differ.", "", "## Execution and copying", "",
            "| Profile/control | Execution time F/P (ms) | Copy time F/P (ms) | PAC nonempty CXL windows | PAC CXL MLP range |",
            "|---|---:|---:|---:|---:|"]
        for m in measurements:
            f,p = m["rows"]["frequency"],m["rows"]["pac"]
            execution = [(float(r["runtime_ns"])-float(r["migration_ns"])-float(r["sampling_ns"]))/1e6 for r in (f,p)]
            lines.append(f'| {m["profile"]}/{m["comparison"]} | {execution[0]:.6f}/{execution[1]:.6f} | '
                f'{float(f["migration_ns"])/1e6:.6f}/{float(p["migration_ns"])/1e6:.6f} | '
                f'{m["pac_nonempty_cxl_windows"]} | {m["pac_mlp_min"]:.6f}–{m["pac_mlp_max"]:.6f} |')
        lines += ["", "Execution time subtraction is a diagnostic, not a zero-migration-cost rerun: placements and "
            "drain barriers are those of the charged-copy run. Copies pause execution, unlike PACT's concurrent "
            "kernel migration; the larger batch can therefore hurt badly here.", "",
            "`paper-all-events` means every CXL demand-load miss is observed; it does not mean exact PACT reproduction. "
            "`paper-sampled` keeps exact aggregate misses/occupancy but observes every 400th CXL miss for page attribution. "
            "It approximates PEBS without hardware filtering or sample loss. Both add 20 bounded bins, access-based "
            "reservoir sampling and a 4,096-page per-update cap. The detailed audit lists remaining differences.", "",
            "No timing coefficients, traces or workload phases were adjusted to obtain a desired speedup. "
            "These comparisons do not establish the paper's 18% hardware result.", "",
            "See [detailed paper audit](../../PAPER_REPRODUCTION.md), [model](../../COMPACT_MODEL.md), "
            "[measurements](measurements.json) and [provenance](provenance.json).", "",
            f"Six comparisons completed in {time.monotonic()-started:.2f} wall seconds (cached input; preprocessing excluded).", ""]
        (OUT / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
        status("complete", comparisons=len(measurements), report=str(OUT/"REPORT.md"))
        print("Completed:", OUT/"REPORT.md")
    except Exception as exc:
        status("failed", error=str(exc))
        raise


if __name__ == "__main__":
    main()
