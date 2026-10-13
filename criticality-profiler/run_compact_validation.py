"""Benchmark once, preprocess full input once, then compare natural/matched PAC."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time

root=Path(__file__).resolve().parent
output=root/"results/compact"
output.mkdir(exist_ok=True)
exe=root/("compact_profiler.exe" if sys.platform=="win32" else "compact_profiler")
raw=root/"traces/graph/bc_bc.kron-5154B.champsimtrace.full.bin"
started=time.monotonic()
deadline=started+3600

def status(stage,**fields):
    (output/"status.json").write_text(json.dumps({"stage":stage,"updated_utc":datetime.now(timezone.utc).isoformat(),
        "wall_seconds":time.monotonic()-started,**fields},indent=2)+"\n")

def call(arguments,log):
    begin=time.monotonic()
    with log.open("w") as handle:
        subprocess.run([str(exe),*map(str,arguments)],stdout=handle,stderr=subprocess.STDOUT,
            check=True,timeout=max(.01,deadline-time.monotonic()))
    return time.monotonic()-begin

def rows(prefix):
    with Path(str(prefix)+".csv").open() as handle:
        result={r["policy"]:r for r in csv.DictReader(handle)}
    assert set(result)=={"cxl","dram","frequency","pac"}
    return result

def validate(prefix,baseline,budget=None):
    result=rows(prefix)
    config=dict(line.split("=",1) for line in Path(str(prefix)+"_config.txt").read_text().splitlines())
    assert int(config["instructions"])==int(baseline["instructions"])
    assert int(config["working_pages"])==int(baseline["working_pages"])
    assert int(config["capacity"])==math.ceil(int(config["working_pages"])/2)
    loads=int(result["cxl"]["cxl_loads"])
    assert loads==int(baseline["loads"]),"Original cache/load domain differs"
    for name,r in result.items():
        assert math.isfinite(float(r["runtime_ns"])) and float(r["runtime_ns"])>0
        assert int(r["dram_loads"])+int(r["cxl_loads"])==loads
        if name not in ("frequency","pac"):continue
        with Path(str(prefix)+f"_{name}_moves.csv").open() as handle: moves=list(csv.DictReader(handle))
        with Path(str(prefix)+f"_{name}_windows.csv").open() as handle: windows=list(csv.DictReader(handle))
        assert len(windows)==int(r["decisions"])
        assert sum(m["direction"]=="CXL_to_DRAM" for m in moves)==int(r["promotions"])
        assert sum(m["direction"]=="DRAM_to_CXL" for m in moves)==int(r["demotions"])
        assert math.isclose(float(r["migration_ns"]),len(moves)*1409.6,abs_tol=1e-4)
        previous=-1
        for w in windows:
            assert int(w["dram_pages"])<=int(config["capacity"])
            assert float(w["sample_ns"])>previous
            assert float(w["resume_ns"])<=float(r["runtime_ns"])
            previous=float(w["resume_ns"])
        if budget is not None:assert int(r["promotions"])==budget
    if budget is not None:assert result["frequency"]["demotions"]==result["pac"]["demotions"]
    return result,config

def main():
    status("benchmarking")
    pilot_cache=root/"traces/graph/kron_5m.cpt"
    prep=call(["--prepare","--trace",raw,"--cache",pilot_cache,"--instructions",5_000_000],output/"pilot_prepare.log")
    replay=call(["--cache",pilot_cache,"--out",output/"kron_5m"],output/"pilot_replay.log")
    old_pilot=json.loads((root/"results/long_bc_kron/pilot_wall.json").read_text())
    benchmark={"instructions":5_000_000,"preprocessing_wall_seconds":prep,"four_policy_wall_seconds":replay,
        "first_run_seconds":prep+replay,"old_instruction_model_wall_seconds":old_pilot["elapsed_seconds"],
        "first_run_speed_ratio":old_pilot["elapsed_seconds"]/(prep+replay),
        "cached_replay_speed_ratio":old_pilot["elapsed_seconds"]/replay}
    (output/"benchmark.json").write_text(json.dumps(benchmark,indent=2)+"\n")
    metadata={"source":str(raw),"bytes":raw.stat().st_size,"mtime_ns":raw.stat().st_mtime_ns,
        "source_manifest":json.loads(raw.with_suffix(".json").read_text()),
        "compiler_executable_sha256":hashlib.sha256(exe.read_bytes()).hexdigest(),
        "model":"coarse_memory_dag_v2","warmup":200000,"epoch_instructions":192}
    cache=root/"traces/graph/kron_full.cpt"
    cache_meta=output/"cache_metadata.json"
    reused=False
    if cache.exists() and cache_meta.exists():
        saved=json.loads(cache_meta.read_text())
        if saved.get("identity")==metadata:
            with cache.open("rb") as handle:
                reused=hashlib.file_digest(handle,"sha256").hexdigest()==saved["cache_sha256"]
    status("preprocessing_full_trace",raw_instructions=metadata["bytes"]//64,benchmark=benchmark)
    full_prep=0 if reused else call(["--prepare","--trace",raw,"--cache",cache],output/"full_prepare.log")
    with cache.open("rb") as handle:cache_hash=hashlib.file_digest(handle,"sha256").hexdigest()
    cache_meta.write_text(json.dumps({"identity":metadata,"cache_sha256":cache_hash,
        "cache_bytes":cache.stat().st_size,"preprocess_wall_seconds":full_prep,"reused":reused},indent=2)+"\n")
    old_prefix=root/"results/full_bc_kron_20ms/full_kron"
    old=rows(old_prefix)
    old_config=dict(line.split("=",1) for line in Path(str(old_prefix)+"_config.txt").read_text().splitlines())
    baseline={"instructions":old_config["instructions"],"working_pages":old_config["working_pages"],
        "loads":old["cxl"]["cxl_loads"]}
    status("comparing",comparison="natural",preprocessing_seconds=full_prep)
    natural_prefix=output/"full_natural_20ms"
    natural_wall=call(["--cache",cache,"--out",natural_prefix,"--window-ns",20_000_000],output/"full_natural.log")
    natural,config=validate(natural_prefix,baseline)
    budget=min(int(natural["frequency"]["promotions"]),int(natural["pac"]["promotions"]))
    status("comparing",comparison="matched",promotion_budget=budget)
    matched_prefix=output/"full_matched_20ms"
    matched_wall=call(["--cache",cache,"--out",matched_prefix,"--window-ns",20_000_000,
        "--promotion-budget",budget],output/"full_matched.log")
    matched,_=validate(matched_prefix,baseline,budget)
    calibration=json.loads((root/"calibration/pact/reference_profile.json").read_text())
    cxl=next(t for t in calibration["tiers"] if t["tier"]=="cxl_emulated")
    lines=["# Fast PAC-versus-frequency validation", "",
        "## Efficiency", "",
        f"5M-instruction benchmark: preprocess {prep:.3f} s, four-policy replay {replay:.3f} s.",
        f"Previous instruction-model pilot: {old_pilot['elapsed_seconds']:.3f} s. First-run ratio: {benchmark['first_run_speed_ratio']:.2f}x.",
        f"Full trace: {int(config['instructions']):,} measured instructions; compact cache {cache.stat().st_size/1e6:.1f} MB versus {raw.stat().st_size/1e9:.1f} GB raw.",
        f"Full preprocessing: {full_prep:.3f} s. Natural comparison: {natural_wall:.3f} s. Matched comparison: {matched_wall:.3f} s.",
        "Subsequent comparisons reuse the compact cache; no raw decoding or cache filtering is repeated.", "",
        "## Full trace at 20 ms, half-footprint DRAM", "",
        "Positive reduction favors PAC. Natural and matched results are both retained.", "",
        "| Comparison | Frequency modeled ms | PAC modeled ms | PAC reduction | Frequency/PAC promotions | Frequency/PAC copy ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for label,r in (("natural",natural),("matched",matched)):
        f,p=r["frequency"],r["pac"];gain=100*(1-float(p["runtime_ns"])/float(f["runtime_ns"]))
        lines.append(f"| {label} | {float(f['runtime_ns'])/1e6:.6f} | {float(p['runtime_ns'])/1e6:.6f} | {gain:+.6f}% | "
            f"{f['promotions']}/{p['promotions']} | {float(f['migration_ns'])/1e6:.6f}/{float(p['migration_ns'])/1e6:.6f} |")
    lines += ["",f"Matched promotion budget: {budget}. Equal actual promotions and demotions were verified.",
        "A zero budget supplies a no-migration control, not evidence about promotion quality.", "",
        "## What is validated", "",
        "The original and compact models have exactly equal load-miss counts and accessed-page footprints.",
        "Tests cover serial/parallel analytical timing, cache filtering, causal weighted dependencies, migration",
        "charges, budget limits, and store exclusion. Equal-frequency low/high-MLP samples select different",
        "pages under PAC; the constant-MLP control ties. These controlled tests validate the mechanism,",
        "not an empirical workload speedup.",
        f"Published PACT hardware-counter data: miss/stall correlation {cxl['miss_stall_correlation']:.3f};",
        f"miss/MLP correlation {cxl['miss_over_mlp_stall_correlation']:.3f}, across {calibration['reference_workloads']} workloads.",
        f"The calibrated CXL stall model's leave-one-out mean absolute error is {cxl['leave_one_out_mean_absolute_percent_error']:.1f}%.",
        "This supports the scoring premise while showing that prediction is approximate.", "",
        "## Limits", "",
        "Compute and cache-hit work is aggregated into conservative 192-instruction epochs; epoch memory",
        "completions are joined by zero-service fences. Within epochs, register miss provenance and same-line",
        "store ordering are retained. This omits cross-epoch pipelining and uses an analytical issue clock",
        "instead of CPU/ROB scheduling. Absolute timing does not match the instruction engine.",
        f"For example, the 5M pilot frequency runtime is {float(rows(output/'kron_5m')['frequency']['runtime_ns'])/1e6:.6f} ms in the compact model",
        "versus about 2.014 ms in the original engine.",
        "The comparisons are fair within this approximation, but do not reproduce the paper's full",
        "multithreaded/Linux runtime or establish its reported 18% speedup. One representative trace region",
        "is evaluated. Latencies are 90/190 ns; sampling cost is zero and migration remains synchronous.",
        "Natural and matched CSVs include all-CXL/all-DRAM references, copy costs, and demand-load counts.",
        "Saved reports are not substitutes for validating a full PACT deployment."]
    (output/"REPORT.md").write_text("\n".join(lines)+"\n")
    status("complete",report=str(output/"REPORT.md"),total_wall_seconds=time.monotonic()-started,
        full_preprocessing_seconds=full_prep,natural_replay_seconds=natural_wall,matched_replay_seconds=matched_wall)

if __name__=="__main__":
    try:main()
    except subprocess.TimeoutExpired:
        status("capped",error="One-hour execution limit reached; completed outputs preserved")
        raise
    except Exception as e:
        status("failed",error=str(e))
        raise
