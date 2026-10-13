"""One complete public kron trace comparison, with a hard one-hour wall cap."""
import csv
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from run_long_bc_kron import validate

root=Path(__file__).resolve().parent
output=root/"results/full_bc_kron_20ms"
output.mkdir(exist_ok=True)
started=time.monotonic()
deadline=started+3600
deadline_utc=datetime.now(timezone.utc)+timedelta(seconds=3600)
prefix=output/"full_kron"

def status(stage,**fields):
    (output/"status.json").write_text(json.dumps({"stage":stage,
        "updated_utc":datetime.now(timezone.utc).isoformat(),"deadline_utc":deadline_utc.isoformat(),
        "wall_cap_seconds":3600,"elapsed_seconds":time.monotonic()-started,**fields},indent=2)+"\n")

def run(command,log_path):
    remaining=deadline-time.monotonic()
    if remaining<=0:
        raise subprocess.TimeoutExpired(command,3600)
    with log_path.open("w") as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=remaining)

def main():
    status("downloading",member="bc.kron-5154B.champsimtrace.xz")
    run([sys.executable,str(root/"fetch_graph_traces.py"),"--archive","bc_traces.zip",
        "--member","bc.kron-5154B.champsimtrace.xz","--full"],output/"download.log")
    trace=root/"traces/graph/bc_bc.kron-5154B.champsimtrace.full.bin"
    manifest=json.loads(trace.with_suffix(".json").read_text())
    assert manifest["full_trace"] and trace.stat().st_size==manifest["records"]*64
    n=manifest["records"]-200_000
    if not 0<n<=2_147_483_647:
        raise RuntimeError(f"Full trace has {n} measured records, outside current instruction-ID range")
    exe=root/("dynamic_profiler.exe" if sys.platform=="win32" else "dynamic_profiler")
    command=[str(exe),"--trace",str(trace),"--out",str(prefix),"--instructions",str(n),
        "--warmup","200000","--streaming","1","--capacity-fraction","0.5",
        "--window-ns","20000000","--dram-ns","90","--cxl-ns","190","--core-ns",str(1/2.2),
        "--pac-k-dram-ns",str(238.0030811389524/2.2),
        "--pac-k-cxl-ns",str(771.0702318170098/2.2),"--batch","64","--reserve","0",
        "--migration-gbps","10","--move-overhead-ns","1000"]
    (output/"plan.json").write_text(json.dumps({"trace_manifest":manifest,
        "instructions":n,"warmup":200000,"complete_trace_member":True,
        "full_multithreaded_application":False,"trace_repetition":False,
        "wall_cap_seconds":3600,"download_included_in_cap":True,"window_ms":20,
        "command":command},indent=2)+"\n")
    status("profiling",instructions=n,total_trace_records=manifest["records"],window_ms=20)
    run(command,output/"profiler.log")
    policies,config=validate(prefix)
    elapsed=time.monotonic()-started
    reduction=100*(1-float(policies["pac"]["runtime_ns"])/float(policies["frequency"]["runtime_ns"]))
    lines=["# Full available bc-kron trace, 20 ms updates", "",
        f"All {manifest['records']:,} records in the public bc.kron-5154B member were consumed:",
        f"200,000 warmup plus {n:,} measured instructions. No truncation, repetition or concatenation.",
        "The member is a representative recorded region, not a full multithreaded application execution.",
        f"DRAM: {config['capacity']} pages out of {config['working_pages']} distinct accessed pages.",
        "90/190 ns DRAM/CXL, 2.2 GHz core assumption, 20 ms update window, streaming execution.",
        f"Total wall time including download: {elapsed/60:.2f} minutes. Hard cap: 60 minutes.", "",
        "| Policy | Modeled runtime ms | Promotions | Demotions | Copy ms | Updates |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in ("cxl","dram","frequency","pac"):
        p=policies[name]
        lines.append(f"| {name} | {float(p['runtime_ns'])/1e6:.6f} | {p['promotions']} | {p['demotions']} | "
            f"{float(p['migration_ns'])/1e6:.6f} | {p['decisions']} |")
    lines += ["",f"PAC modeled runtime reduction versus frequency: {reduction:+.6f}%.",
        "This natural adaptive comparison does not enforce matched migration counts.",
        "All four policies consumed the same measured instructions. Capacity, load conservation,",
        "migration-count/cost and event-time validation passed. Simplified cache, single instruction",
        "stream, synchronous migration and zero sampling-processing cost remain limitations."]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
    status("complete",instructions=n,reduction_percent=reduction,report=str(output/"REPORT.md"))

if __name__=="__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        status("capped",message="One-hour wall-clock limit reached; active child terminated; completed outputs preserved.")
        (output/"REPORT.md").write_text("# Full bc-kron run capped\n\nThe one-hour wall limit was reached.\n"
            "Any rows in full_kron.csv are completed whole-trace policies; missing rows are incomplete.\n"
            "Compare PAC and frequency only if both rows are present with identical instruction coverage.\n"
            "Download/profiling logs and plan metadata are retained. No partial result is labelled a full run.\n")
    except Exception as error:
        status("failed",error=str(error))
        raise
