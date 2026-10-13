"""Unattended, pilot-sized continuous trace campaign; no polling required."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parent
output = root / "results/long_bc_kron"
output.mkdir(exist_ok=True)
status_path = output / "status.json"

def save_status(stage, **fields):
    status_path.write_text(json.dumps({"stage":stage,
        "updated_utc":datetime.now(timezone.utc).isoformat(), **fields}, indent=2)+"\n")

def validate(prefix, budget=None):
    with Path(str(prefix)+".csv").open() as handle:
        policies = {r["policy"]:r for r in csv.DictReader(handle)}
    assert set(policies) == {"cxl","dram","frequency","pac"}
    config = dict(line.split("=",1) for line in Path(str(prefix)+"_config.txt").read_text().splitlines())
    assert int(config["capacity"]) == math.ceil(int(config["working_pages"])*0.5)
    loads = int(policies["cxl"]["cxl_loads"])
    for name, p in policies.items():
        assert math.isfinite(float(p["runtime_ns"])) and float(p["runtime_ns"]) > 0
        assert int(p["cxl_loads"])+int(p["dram_loads"]) == loads
        if name not in ("frequency","pac"):
            continue
        with Path(str(prefix)+f"_{name}_moves.csv").open() as handle:
            moves = list(csv.DictReader(handle))
        with Path(str(prefix)+f"_{name}_windows.csv").open() as handle:
            windows = list(csv.DictReader(handle))
        assert len(windows) == int(p["decisions"])
        assert sum(m["direction"]=="CXL_to_DRAM" for m in moves) == int(p["promotions"])
        assert sum(m["direction"]=="DRAM_to_CXL" for m in moves) == int(p["demotions"])
        assert math.isclose(float(p["migration_ns"]),len(moves)*1409.6,abs_tol=1e-4)
        previous = -1
        for w in windows:
            assert int(w["dram_pages"]) <= int(config["capacity"])
            assert float(w["sample_ns"]) > previous
            assert float(w["resume_ns"]) <= float(p["runtime_ns"])
            previous = float(w["resume_ns"])
        if budget is not None:
            assert int(p["promotions"]) == budget, "Matched budget was not reached"
    if budget is not None:
        assert policies["frequency"]["demotions"] == policies["pac"]["demotions"], "Matched copy counts differ"
    return policies, config

def main():
    pilot = json.loads((output/"pilot_wall.json").read_text())
    # Eight full comparisons: four natural policies and four equal-promotion controls.
    planned = max(1_000_000,int(1050*pilot["instructions"]/(8*pilot["elapsed_seconds"])/1_000_000)*1_000_000)
    trace = root/"traces/graph/bc_bc.kron-5154B.champsimtrace.bin"
    save_status("downloading",planned_instructions=planned,target_profiling_seconds=1050)
    with (output/"download.log").open("w") as log:
        subprocess.run([sys.executable,str(root/"fetch_graph_traces.py"),"--archive","bc_traces.zip",
            "--member","bc.kron-5154B.champsimtrace.xz","--records",str(planned+200_000),"--allow-short"],
            stdout=log,stderr=subprocess.STDOUT,check=True)
    trace_manifest = json.loads(trace.with_suffix(".json").read_text())
    n = min(planned,trace_manifest["records"]-200_000)
    if n <= 0:
        raise RuntimeError("Not enough real records after warmup")
    exe = root/("dynamic_profiler.exe" if sys.platform=="win32" else "dynamic_profiler")
    plan = {"instructions_per_comparison":n,"planned_instructions":planned,"comparisons":8,
        "estimated_profiling_seconds":8*n/pilot["instructions"]*pilot["elapsed_seconds"],
        "target_wall_seconds":1050,"duration_kind":"profiler wall time, not modeled workload runtime",
        "download_time_excluded":True,"trace_looping":False,"trace_manifest":trace_manifest,
        "capacity_fraction":0.5,"capacity_basis":"distinct accessed virtual pages in measured trace prefix; not full application RSS",
        "windows_ms":[20,5,1,0.2],"pilot":pilot,
        "executable_sha256":hashlib.sha256(exe.read_bytes()).hexdigest()}
    (output/"plan.json").write_text(json.dumps(plan,indent=2)+"\n")
    rows=[]
    started=time.monotonic()
    for window in (20_000_000,5_000_000,1_000_000,200_000):
        natural=None
        for matched in (False,True):
            budget=min(int(natural["frequency"]["promotions"]),int(natural["pac"]["promotions"])) if matched else None
            label="matched" if matched else "natural"
            prefix=output/f"bc_kron5154_n{n}_window{window}_{label}"
            command=[str(exe),"--trace",str(trace),"--out",str(prefix),"--instructions",str(n),
                "--warmup","200000","--streaming","1","--capacity-fraction","0.5",
                "--dram-ns","90","--cxl-ns","190","--core-ns",str(1/2.2),
                "--pac-k-dram-ns",str(238.0030811389524/2.2),
                "--pac-k-cxl-ns",str(771.0702318170098/2.2),"--window-ns",str(window),
                "--batch","64","--reserve","0","--migration-gbps","10","--move-overhead-ns","1000"]
            if matched:
                command += ["--promotion-budget",str(budget)]
            save_status("profiling",instructions=n,window_ms=window/1e6,comparison=label,
                completed_comparisons=len(rows),estimated_profiling_seconds=plan["estimated_profiling_seconds"])
            start=time.monotonic()
            with Path(str(prefix)+".log").open("w") as log:
                subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
            policies,config=validate(prefix,budget)
            if not matched:
                natural=policies
            row={"comparison":label,"instructions":n,"window_ms":window/1e6,"matched_promotions":budget,
                "working_pages":config["working_pages"],"dram_pages":config["capacity"],
                "wall_seconds":time.monotonic()-start,"source_prefix":prefix.name,
                "reduction_percent":100*(1-float(policies["pac"]["runtime_ns"])/float(policies["frequency"]["runtime_ns"]))}
            for mode,p in policies.items():
                for field in ("runtime_ns","promotions","demotions","migration_ns","decisions"):
                    row[f"{mode}_{field}"]=p[field]
            rows.append(row)
            with (output/"campaign.csv").open("w",newline="") as handle:
                writer=csv.DictWriter(handle,fieldnames=list(row));writer.writeheader();writer.writerows(rows)
    elapsed=time.monotonic()-started
    lines=["# Longer continuous bc-kron campaign", "",
        f"{n:,} instructions per comparison, plus 200,000 warmup. Eight comparisons.",
        f"Actual profiling wall time: {elapsed/60:.2f} minutes; pilot estimate: {plan['estimated_profiling_seconds']/60:.2f} minutes.",
        "Download time is separate. No trace repetition or concatenation.",
        "DRAM holds half the distinct accessed pages, including cache-hit pages.",
        "This is an address-footprint ratio, not the original application's RSS ratio.",
        "90/190 ns memory, 2.2 GHz core assumption, 238/771-cycle fitted PAC coefficients converted at that clock.",
        "One instruction stream/cache and synchronous migrations remain model limitations.", "",
        "Positive reduction favors PAC. Natural runs retain adaptive candidate counts;",
        "matched runs cap both policies at the smaller natural promotion total and verify both reach it.",
        "Zero matched promotions indicate no migration experiment at that interval.", "",
        "| Comparison | Window ms | DRAM pages | Frequency ms | PAC ms | Reduction | Frequency/PAC promotions | PAC updates |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for r in rows:
        lines.append(f"| {r['comparison']} | {r['window_ms']:g} | {r['dram_pages']} | "
            f"{float(r['frequency_runtime_ns'])/1e6:.3f} | {float(r['pac_runtime_ns'])/1e6:.3f} | "
            f"{r['reduction_percent']:+.3f}% | {r['frequency_promotions']}/{r['pac_promotions']} | {r['pac_decisions']} |")
    lines += ["", "All comparisons passed capacity, load conservation, event-time, and migration accounting checks.",
        "Matched runs additionally passed equal-promotion and equal-demotion checks.",
        "Budget matching equalizes counts, not migration times or instruction positions.",
        "Baseline systems such as Colloid/NBT are not implemented. Sampling processing cost remains zero.",
        "Raw outcomes: [campaign.csv](campaign.csv). Provenance and pilot sizing: [plan.json](plan.json)."]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
    save_status("complete",instructions=n,completed_comparisons=len(rows),profiling_seconds=elapsed,
        report=str(output/"REPORT.md"))

if __name__=="__main__":
    try:
        main()
    except Exception as error:
        save_status("failed",error=str(error))
        raise
