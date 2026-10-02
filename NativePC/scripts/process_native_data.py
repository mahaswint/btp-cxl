#!/usr/bin/env python3

from pathlib import Path
import csv
import re
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data"
OUT = ROOT / "processed_data"

WORKLOADS = [
    "llama_cpp",
    "bert",
    "dlrm",
    "ann",
    "stream",
    "pointer_chase",
    "kmeans",
]

EVENT_FILES = {
    "core_cache": "core_cache.csv",
    "memory_traffic": "memory_traffic.csv",
    "memory_retired": "memory_retired.csv",
    "tlb": "tlb.csv",
}

# Events we want to preserve explicitly.
EVENT_ALIASES = {
    "cycles": "cycles",
    "instructions": "instructions",
    "cache-references": "cache_references",
    "cache-misses": "cache_misses",
    "l2_rqsts.all_demand_data_rd": "l2_demand_reads",
    "l2_rqsts.demand_data_rd_miss": "l2_demand_read_misses",
    "mem-loads": "mem_loads",
    "mem-stores": "mem_stores",
    "offcore_requests_outstanding.cycles_with_data_rd":
        "offcore_data_read_outstanding_cycles",
    "mem_load_retired.l1_miss": "l1_load_misses",
    "mem_load_retired.l2_miss": "l2_load_misses",
    "mem_load_retired.l3_miss": "l3_load_misses",
    "dtlb_load_misses.walk_completed": "dtlb_load_walks",
    "dtlb_store_misses.walk_completed": "dtlb_store_walks",
}


def read_perf_csv(path: Path):
    rows = []

    if not path.exists():
        return rows

    with path.open("r", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue

            # perf -x, format:
            # value,unit,event,time_running_pct,...
            p = raw.split(",")

            if len(p) < 4:
                continue

            try:
                value = float(p[0])
            except ValueError:
                continue

            event = p[2].strip()
            try:
                time_running = float(p[4]) if len(p) > 4 and p[4] else None
            except ValueError:
                time_running = None

            rows.append({
                "event_raw": event,
                "value": value,
                "time_running_pct": time_running,
                "raw_line": raw,
            })

    return rows


def normalize_event(event):
    event = event.rstrip("/")
    return EVENT_ALIASES.get(event, event.replace("/", "_").replace(".", "_"))


def extract_run(run_dir: Path):
    result = {
        "workload": run_dir.parent.parent.name,
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
    }

    # Metadata / command
    metadata = run_dir / "metadata.txt"
    command = run_dir / "command.txt"

    if metadata.exists():
        text = metadata.read_text(errors="replace")
        for line in text.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                result["meta_" + k.strip()] = v.strip()

    if command.exists():
        result["command"] = command.read_text(errors="replace").strip()

    # Status
    status = run_dir / "status.csv"
    if status.exists():
        text = status.read_text(errors="replace")
        result["status_text"] = text.replace("\n", " | ")

        failed = False
        for line in text.splitlines():
            if line.strip() and not line.lower().startswith("group"):
                if ",0" not in line and not line.endswith(",0"):
                    failed = True
        result["status_ok"] = not failed

    # Collect events.
    event_values = {}
    event_coverage = {}

    for group, filename in EVENT_FILES.items():
        path = run_dir / filename

        for row in read_perf_csv(path):
            key = normalize_event(row["event_raw"])

            # Keep first occurrence unless duplicate.
            event_values.setdefault(key, row["value"])

            if row["time_running_pct"] is not None:
                event_coverage[key] = row["time_running_pct"]

    result.update(event_values)

    for k, v in event_coverage.items():
        result[k + "_coverage_pct"] = v

    # Derived metrics.
    cycles = result.get("cycles")
    instructions = result.get("instructions")

    def add(name, value):
        result[name] = value

    if cycles and cycles > 0 and instructions is not None:
        add("ipc", instructions / cycles)
        add("instructions_per_million_cycles",
            instructions / cycles * 1_000_000)

    if instructions and instructions > 0:
        if "cache_misses" in result:
            add("cache_misses_per_million_inst",
                result["cache_misses"] / instructions * 1e6)

        if "l2_demand_read_misses" in result:
            add("l2_misses_per_million_inst",
                result["l2_demand_read_misses"] / instructions * 1e6)

        if "l3_load_misses" in result:
            add("l3_misses_per_million_inst",
                result["l3_load_misses"] / instructions * 1e6)

        if "dtlb_load_walks" in result:
            add("dtlb_load_walks_per_million_inst",
                result["dtlb_load_walks"] / instructions * 1e6)

        if "dtlb_store_walks" in result:
            add("dtlb_store_walks_per_million_inst",
                result["dtlb_store_walks"] / instructions * 1e6)

        if "mem_stores" in result:
            add("stores_per_million_inst",
                result["mem_stores"] / instructions * 1e6)

        if "offcore_data_read_outstanding_cycles" in result:
            add(
                "offcore_outstanding_per_inst",
                result["offcore_data_read_outstanding_cycles"] /
                instructions
            )

    if cycles and cycles > 0:
        if "offcore_data_read_outstanding_cycles" in result:
            add(
                "offcore_outstanding_cycle_fraction",
                result["offcore_data_read_outstanding_cycles"] / cycles
            )

    # Flag questionable coverage.
    coverage_cols = [
        c for c in result if c.endswith("_coverage_pct")
    ]

    result["min_primary_coverage_pct"] = None
    if coverage_cols:
        vals = [
            result[c] for c in coverage_cols
            if isinstance(result[c], (int, float))
            and c not in {
                "topdown_mem_bound_coverage_pct",
                "topdown_be_bound_coverage_pct"
            }
        ]
        if vals:
            result["min_primary_coverage_pct"] = min(vals)

    result["coverage_warning"] = (
        result["min_primary_coverage_pct"] is not None
        and result["min_primary_coverage_pct"] < 90
    )

    return result


def find_run_dirs(workload):
    base = RAW / workload / "native"

    if not base.exists():
        return []

    dirs = [
        p for p in base.iterdir()
        if p.is_dir() and re.match(r"^\d{8}_\d{6}", p.name)
    ]

    return sorted(dirs)


def main():
    OUT.mkdir(exist_ok=True)

    all_rows = []
    inventory_rows = []

    for workload in WORKLOADS:
        dirs = find_run_dirs(workload)

        print(f"\n=== {workload} ===")
        print(f"Found {len(dirs)} run directories")

        for d in dirs:
            row = extract_run(d)
            all_rows.append(row)

            inventory_rows.append({
                "workload": workload,
                "run_id": d.name,
                "run_dir": str(d),
                "status_ok": row.get("status_ok"),
                "min_primary_coverage_pct":
                    row.get("min_primary_coverage_pct"),
                "coverage_warning":
                    row.get("coverage_warning"),
            })

    df = pd.DataFrame(all_rows)
    inv = pd.DataFrame(inventory_rows)

    # Save everything discovered. Nothing is deleted or modified.
    df.to_csv(OUT / "run_level_all_discovered.csv", index=False)
    inv.to_csv(OUT / "run_inventory_all_discovered.csv", index=False)

    print("\n=== DISCOVERED RUNS ===")
    print(
        inv.groupby("workload")
        .size()
        .to_string()
    )

    print("\n=== STATUS / COVERAGE ===")
    print(inv.to_string(index=False))

    # Keep only successful runs with adequate primary counter coverage.
    good = inv[
        (inv["status_ok"] == True) &
        (inv["coverage_warning"] != True)
    ].copy()

    # For now do NOT automatically choose the 5 campaign runs.
    # We inspect the discovered set first.
    good.to_csv(OUT / "run_inventory_good.csv", index=False)

    print("\n=== GOOD CANDIDATE RUNS ===")
    print(good.groupby("workload").size().to_string())

    # Basic workload-level summary across all discovered runs.
    numeric_candidates = [
        "cycles",
        "instructions",
        "ipc",
        "cache_references",
        "cache_misses",
        "l2_demand_reads",
        "l2_demand_read_misses",
        "mem_stores",
        "offcore_data_read_outstanding_cycles",
        "l1_load_misses",
        "l2_load_misses",
        "l3_load_misses",
        "dtlb_load_walks",
        "dtlb_store_walks",
        "cache_misses_per_million_inst",
        "l2_misses_per_million_inst",
        "l3_misses_per_million_inst",
        "dtlb_load_walks_per_million_inst",
        "dtlb_store_walks_per_million_inst",
        "stores_per_million_inst",
        "offcore_outstanding_per_inst",
        "offcore_outstanding_cycle_fraction",
    ]

    available = [c for c in numeric_candidates if c in df.columns]

    if available:
        summary = (
            df.groupby("workload")[available]
            .agg(["mean", "std", "min", "max"])
        )
        summary.to_csv(OUT / "discovered_workload_summary.csv")

    print("\nCreated:")
    print(OUT / "run_level_all_discovered.csv")
    print(OUT / "run_inventory_all_discovered.csv")
    print(OUT / "run_inventory_good.csv")
    print(OUT / "discovered_workload_summary.csv")


if __name__ == "__main__":
    main()
