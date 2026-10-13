"""Fixed-seed random alpha sensitivity, at 20 ms only, with pinned C++ sources."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results/synthetic_streams/random_decay_20ms"
SEED = 20261013
RNG = random.Random(SEED)
RANDOM_ALPHAS = [round(RNG.uniform(.1, .95), 3) for _ in range(6)]
ALPHAS = sorted(set(RANDOM_ALPHAS + [.7, 1.0]))
SOURCE_FILES = ["synthetic_stream_profiler.cpp", "dynamic_profiler.cpp",
    "trace_profiler.cpp", "dynamic_model.h", "streaming_trace.h"]


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot = OUT / "source"
    snapshot.mkdir(exist_ok=True)
    started = time.monotonic()
    deadline = started + 3600
    def status(stage, **extra):
        (OUT/"status.json").write_text(json.dumps({"stage": stage,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "wall_seconds": time.monotonic()-started, **extra}, indent=2)+"\n")
    def call(args, log):
        with log.open("w") as handle:
            subprocess.run(list(map(str,args)), check=True, stdout=handle,
                stderr=subprocess.STDOUT, timeout=max(.01, deadline-time.monotonic()))
    try:
        status("building_source_snapshot")
        for name in SOURCE_FILES:
            shutil.copyfile(ROOT/name, snapshot/name)
        compiler = shutil.which("g++")
        if not compiler: raise RuntimeError("C++ compiler not found")
        exe = OUT/("sweep_profiler.exe" if sys.platform == "win32" else "sweep_profiler")
        call([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-pedantic",
            snapshot/"synthetic_stream_profiler.cpp", "-o", exe], OUT/"build.log")
        version = subprocess.run([compiler,"--version"], check=True, capture_output=True, text=True).stdout
        provenance = {"seed": SEED, "distribution": "Uniform(0.1, 0.95), rounded to 3 decimals",
            "random_alphas_selected_before_runs": RANDOM_ALPHAS,
            "reference_alphas": [.7, 1.0], "window_ms": 20, "rounds": 12,
            "matched_decay_for_both_policies": True,
            "source_files": [{"name": n, "sha256": hashlib.sha256((snapshot/n).read_bytes()).hexdigest()} for n in SOURCE_FILES],
            "compiler_version": version,
            "executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
            "policy_note": "This pinned source decays historical reservoir values together with page scores. Older saved alpha<1 runs predate that shared-code correction; use this sweep's freshly run references for comparison."}
        (OUT/"provenance.json").write_text(json.dumps(provenance, indent=2)+"\n")
        plan = [(a,w) for a in ALPHAS for w in (8,16)]
        # Constant-overlap controls at the extreme random values and alpha=.7.
        plan += [(a,1) for a in sorted({min(RANDOM_ALPHAS),max(RANDOM_ALPHAS),.7})]
        (OUT/"plan.json").write_text(json.dumps({"cases": [{"alpha":a,"mlp_width":w} for a,w in plan],
            "window_ms":20,"one_hour_cap":True}, indent=2)+"\n")
        measurements=[]
        summary_path=OUT/"summary.csv"
        with summary_path.open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=["alpha","mlp_width","frequency_ms","pac_ms",
                "runtime_reduction_percent","frequency_promotions","pac_promotions",
                "frequency_updates","pac_updates","frequency_critical_pages","pac_critical_pages","case_directory"])
            writer.writeheader();handle.flush()
            for i,(alpha,width) in enumerate(plan):
                case=OUT/f"alpha_{alpha:.3f}".replace(".","_")/f"mlp{width}"
                case.mkdir(parents=True,exist_ok=True)
                status("running",completed=i,total=len(plan),alpha=alpha,mlp_width=width)
                begin=time.monotonic()
                call([exe,"--alpha",alpha,"--window-ms",20,"--rounds",12,
                    "--scenario",f"hot_first_mlp{width}","--out",case],case/"run.log")
                rows={r["policy"]:r for r in read_csv(case/"summary.csv")}
                assert set(rows)=={"frequency","pac"}
                baseline=ROOT/f"results/synthetic_streams/alpha_0_7/{'control' if width==1 else 'mlp'+str(width)}/streams.csv"
                assert read_csv(case/"streams.csv")==read_csv(baseline),"Workload changed"
                for policy,r in rows.items():
                    assert abs(float(r["alpha"])-alpha)<1e-12 and float(r["window_ms"])==20
                    assert int(r["rounds"])==12 and int(r["total_loads"])==25313280
                    assert int(r["promotions"])==int(r["demotions"])==1024
                    assert math.isfinite(float(r["runtime_ns"])) and float(r["runtime_ns"])>0
                    windows=read_csv(case/f"hot_first_mlp{width}_{policy}_windows.csv")
                    assert len(windows)==int(r["updates"])
                    resume=0
                    for window in windows:
                        gap=float(window["sample_ns"])-resume
                        assert 20000000-1e-5<=gap<=20000190+1e-5
                        assert int(window["dram_pages"])==1024
                        resume=float(window["resume_ns"])
                    assert resume<=float(r["runtime_ns"])
                f,p=rows["frequency"],rows["pac"]
                assert f["migration_ns"]==p["migration_ns"]
                if width==1:
                    assert f["runtime_ns"]==p["runtime_ns"],"Constant-MLP control diverged"
                    assert read_csv(case/"hot_first_mlp1_frequency_final_pages.csv")==read_csv(case/"hot_first_mlp1_pac_final_pages.csv")
                measurement={"alpha":alpha,"mlp_width":width,
                    "frequency_ms":float(f["runtime_ns"])/1e6,"pac_ms":float(p["runtime_ns"])/1e6,
                    "runtime_reduction_percent":100*(1-float(p["runtime_ns"])/float(f["runtime_ns"])),
                    "frequency_promotions":int(f["promotions"]),"pac_promotions":int(p["promotions"]),
                    "frequency_updates":int(f["updates"]),"pac_updates":int(p["updates"]),
                    "frequency_critical_pages":int(f["critical_dram_pages"]),"pac_critical_pages":int(p["critical_dram_pages"]),
                    "case_directory":str(case.relative_to(OUT))}
                writer.writerow(measurement);handle.flush()
                measurements.append({**measurement,"rows":rows,"wall_seconds":time.monotonic()-begin})
                (OUT/"measurements.json").write_text(json.dumps(measurements,indent=2)+"\n")
        lookup={(m["alpha"],m["mlp_width"]):m for m in measurements}
        lines=["# Random decay sensitivity: 20 ms only", "",
            f"Six random alpha values were drawn before outcomes using seed {SEED}: "+", ".join(map(str,RANDOM_ALPHAS))+". "
            "Each alpha is fixed throughout its run. Alpha 0.7 and 1.0 are fresh reference runs. "
            "Both PAC and frequency receive the same alpha. Every case uses the same synthetic streams, 12 rounds, "
            "25,313,280 loads, 90/190 ns service times and 4 MiB DRAM.", "",
            "| Alpha | Kind | MLP 8 runtime reduction | MLP 16 runtime reduction | PAC serial pages in DRAM, MLP 8/16 |",
            "|---|---|---:|---:|---:|"]
        for alpha in ALPHAS:
            a,b=lookup[alpha,8],lookup[alpha,16]
            lines.append(f"| {alpha:.3f} | {'random' if alpha in RANDOM_ALPHAS else 'reference'} | "
                f"{a['runtime_reduction_percent']:+.6f}% | {b['runtime_reduction_percent']:+.6f}% | "
                f"{a['pac_critical_pages']}/{b['pac_critical_pages']} |")
        lines += ["", "Positive reduction favors PAC. Every case actually reaches 1,024 promotions and 1,024 demotions "
            "for each policy, with equal 2.886861 ms copy charges. Placement freezes after that preset budget is exhausted. "
            "All outcomes are retained; this is parameter sensitivity, not independent stochastic trials or a confidence interval.", "",
            "The shared policy source now decays histogram reservoir values as well as tracked page scores. "
            "These fresh references use that same build. Historical alpha<1 reports used the earlier reservoir behavior "
            "and should not be directly combined with this sweep. Source snapshots and checksums are retained.", "",
            "Constant-MLP controls at the minimum/maximum random alpha and alpha 0.7 matched exactly in runtime and placement. "
            "Analytical timing, decay, workload identity, load conservation, observation spacing, capacity and equal migration checks passed.", "",
            "Synthetic LLC-miss streams and analytical batch execution demonstrate the scoring mechanism under controlled assumptions. "
            "They do not reproduce the complete PACT runtime or the paper's hardware results.", "",
            "[All runtimes and counts](summary.csv) · [Detailed measurements](measurements.json) · [Preselected run plan](plan.json) · "
            "[Source/build provenance](provenance.json)", "",f"Completed {len(plan)} cases in {time.monotonic()-started:.2f} wall seconds.",""]
        (OUT/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
        status("complete",completed=len(plan),total=len(plan),report=str(OUT/"REPORT.md"))
        print("Completed:",OUT/"REPORT.md")
    except Exception as exc:
        status("failed",error=str(exc))
        raise


if __name__=="__main__":
    main()
