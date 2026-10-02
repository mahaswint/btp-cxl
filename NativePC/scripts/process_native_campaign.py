#!/usr/bin/env python3
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data"
OUT = ROOT / "processed_data"
OUT.mkdir(exist_ok=True)

CAMPAIGN_IDS = {
    "llama_cpp": ["20260901_151915_llama_cpp","20260901_152010_llama_cpp","20260901_152105_llama_cpp","20260901_152200_llama_cpp","20260901_152254_llama_cpp"],
    "bert": ["20260901_152349_bert","20260901_152746_bert","20260901_153137_bert","20260901_153530_bert","20260901_153919_bert"],
    "dlrm": ["20260901_154313_dlrm","20260901_154337_dlrm","20260901_154400_dlrm","20260901_154423_dlrm","20260901_154446_dlrm"],
    "ann": ["20260901_154510_ann","20260901_154727_ann","20260901_154947_ann","20260901_155207_ann","20260901_155427_ann"],
    "stream": ["20260901_155648_stream","20260901_155711_stream","20260901_155735_stream","20260901_155759_stream","20260901_155823_stream"],
    "pointer_chase": ["20260901_155847_pointer_chase","20260901_155906_pointer_chase","20260901_155926_pointer_chase","20260901_155945_pointer_chase","20260901_160004_pointer_chase"],
    "kmeans": ["20260901_160023_kmeans","20260901_160030_kmeans","20260901_160037_kmeans","20260901_160043_kmeans","20260901_160050_kmeans"],
}

GROUPS = ["core_cache", "memory_traffic", "memory_retired", "tlb"]

EVENT_MAP = {
    "cycles": "cycles",
    "instructions": "instructions",
    "cache-references": "cache_references",
    "cache-misses": "cache_misses",
    "l2_rqsts.all_demand_data_rd": "l2_demand_reads",
    "l2_rqsts.demand_data_rd_miss": "l2_demand_read_misses",
    "mem-loads": "mem_loads",
    "mem-stores": "mem_stores",
    "offcore_requests_outstanding.cycles_with_data_rd": "offcore_outstanding_cycles",
    "mem_load_retired.l1_miss": "l1_load_misses",
    "mem_load_retired.l2_miss": "l2_load_misses",
    "mem_load_retired.l3_miss": "l3_load_misses",
    "dtlb_load_misses.walk_completed": "dtlb_load_walks",
    "dtlb_store_misses.walk_completed": "dtlb_store_walks",
}

def parse(path):
    out = []
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        p = line.split(",")
        if len(p) < 5:
            continue
        try:
            value = float(p[0])
            coverage = float(p[4])
        except ValueError:
            continue
        event = p[2].strip().rstrip("/")
        if event.startswith("cpu_core/"):
            event = event[len("cpu_core/"):]
        if event in EVENT_MAP:
            out.append((EVENT_MAP[event], value, coverage))
    return out

rows = []
manifest = []

for workload, run_ids in CAMPAIGN_IDS.items():
    for rep, run_id in enumerate(run_ids, 1):
        run_dir = RAW / workload / "native" / run_id
        status = (run_dir / "status.csv").read_text(errors="replace")
        status_ok = all(
            not line.strip() or line.startswith("group") or line.rstrip().endswith(",0")
            for line in status.splitlines()
        )
        manifest.append({
            "workload": workload,
            "repetition": rep,
            "run_id": run_id,
            "status_ok": status_ok
        })

        for group in GROUPS:
            for event, value, coverage in parse(run_dir / f"{group}.csv"):
                rows.append({
                    "workload": workload,
                    "repetition": rep,
                    "run_id": run_id,
                    "perf_group": group,
                    "event": event,
                    "value": value,
                    "coverage_pct": coverage
                })

long_df = pd.DataFrame(rows)
manifest_df = pd.DataFrame(manifest)

long_df.to_csv(OUT / "raw_counters_long.csv", index=False)
manifest_df.to_csv(OUT / "campaign_manifest.csv", index=False)

# group-preserving wide table
wide = long_df.pivot_table(
    index=["workload","repetition","run_id","perf_group"],
    columns="event",
    values="value",
    aggfunc="first"
).reset_index()

wide.to_csv(OUT / "group_level_counters.csv", index=False)

# derive metrics using cycles/instructions from SAME perf group
m = wide.copy()

m["ipc"] = m["instructions"] / m["cycles"]

for col in [
    "cache_misses",
    "l2_demand_read_misses",
    "l1_load_misses",
    "l2_load_misses",
    "l3_load_misses",
    "dtlb_load_walks",
    "dtlb_store_walks",
    "mem_stores",
]:
    if col in m:
        m[f"{col}_per_million_inst"] = m[col] / m["instructions"] * 1e6

if "offcore_outstanding_cycles" in m:
    m["offcore_outstanding_fraction"] = (
        m["offcore_outstanding_cycles"] / m["cycles"]
    )

m.to_csv(OUT / "normalized_metrics_by_group.csv", index=False)

# Build one row per run, selecting each metric from its intended group
wanted = {
    "ipc": "core_cache",
    "cache_misses_per_million_inst": "core_cache",
    "l2_demand_read_misses_per_million_inst": "core_cache",
    "offcore_outstanding_fraction": "memory_traffic",
    "mem_stores_per_million_inst": "memory_traffic",
    "l1_load_misses_per_million_inst": "memory_retired",
    "l2_load_misses_per_million_inst": "memory_retired",
    "l3_load_misses_per_million_inst": "memory_retired",
    "dtlb_load_walks_per_million_inst": "tlb",
    "dtlb_store_walks_per_million_inst": "tlb",
}

run_rows = []

for _, r in manifest_df.iterrows():
    x = r.to_dict()
    for metric, group in wanted.items():
        z = m[
            (m.workload == r.workload) &
            (m.run_id == r.run_id) &
            (m.perf_group == group)
        ]
        x[metric] = z.iloc[0][metric] if len(z) and metric in z.columns else np.nan
    run_rows.append(x)

run_df = pd.DataFrame(run_rows)
run_df.to_csv(OUT / "run_level_metrics.csv", index=False)

summary = []

for workload, g in run_df.groupby("workload"):
    for metric in wanted:
        vals = pd.to_numeric(g[metric], errors="coerce").dropna()
        if len(vals):
            summary.append({
                "workload": workload,
                "metric": metric,
                "n": len(vals),
                "mean": vals.mean(),
                "std": vals.std(),
                "cv_pct": vals.std() / abs(vals.mean()) * 100 if vals.mean() else np.nan
            })

pd.DataFrame(summary).to_csv(OUT / "workload_summary.csv", index=False)

print("Done.")
print("\nRuns:")
print(manifest_df.groupby("workload").size())
print("\nOutput:")
for f in sorted(OUT.glob("*.csv")):
    print(f)
