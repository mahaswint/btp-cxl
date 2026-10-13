"""Validate every graph case and report results without outcome filtering."""
import argparse
import csv
import math
from pathlib import Path

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--representative", action="store_true")
args = parser.parse_args()
output = root / "results" / ("graph_representative" if args.representative else "graph")
with (output / "campaign.csv").open() as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 12
lines = ["# Public GAP graph-workload results", "",
    "Real public bc-kron, bc-twitter, and tc-twitter instruction traces, evaluated",
    "using the existing dynamic PAC/frequency model. Each run has 200k warmup plus",
    "12 million runtime instructions. All cases were chosen before measuring outcomes.",
    "Regions selected by highest published execution weight." if args.representative else "Regions selected by earliest available instruction label.", "",
    "Sources, selected regions, reproduction, and limitations are in",
    "[GRAPH_WORKLOADS.md](../../GRAPH_WORKLOADS.md). Results are modeled, not hardware",
    "measurements or reproductions of PACT's reported speedups.", "",
    "Defaults: 80 ns DRAM, 250 ns CXL, 16 memory slots, 64-page promotion batches,",
    "10 GB/s copy throughput, 1000 ns per-page overhead, no extra eager reserve.", "",
    "## Paper-size 20 ms sampling windows", "",
    "Positive reduction means PAC is faster than dynamic frequency.", "",
    "| Trace | DRAM pages | Frequency ms | PAC ms | PAC reduction | PAC updates | CXL MLP range |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]

for row in rows:
    trace, window, capacity = row["trace"], int(row["window_ns"]), int(row["capacity_pages"])
    prefix = output / f"{trace}_window{window}_cap{capacity}"
    with Path(str(prefix) + ".csv").open() as f:
        policies = {r["policy"]: r for r in csv.DictReader(f)}
    expected_loads = int(policies["cxl"]["cxl_loads"])
    for name, policy in policies.items():
        assert int(policy["dram_loads"]) + int(policy["cxl_loads"]) == expected_loads
        if name not in ("pac", "frequency"):
            continue
        with Path(str(prefix) + f"_{name}_windows.csv").open() as f:
            windows = list(csv.DictReader(f))
        with Path(str(prefix) + f"_{name}_moves.csv").open() as f:
            moves = list(csv.DictReader(f))
        assert len(windows) == int(policy["decisions"])
        assert sum(m["direction"] == "CXL_to_DRAM" for m in moves) == int(policy["promotions"])
        assert sum(m["direction"] == "DRAM_to_CXL" for m in moves) == int(policy["demotions"])
        assert math.isclose(float(policy["migration_ns"]), len(moves) * 1409.6, rel_tol=1e-9, abs_tol=1e-5)
        previous = -1
        for w in windows:
            assert int(w["dram_pages"]) <= capacity
            assert float(w["sample_ns"]) > previous
            assert float(w["resume_ns"]) <= float(policy["runtime_ns"])
            previous = float(w["resume_ns"])

def table_row(r):
    return f"| {r['trace']} | {r['capacity_pages']} | {float(r['frequency_ns'])/1e6:.3f} | " \
        f"{float(r['pac_ns'])/1e6:.3f} | {float(r['reduction_percent']):+.3f}% | {r['pac_decisions']} | " \
        f"{float(r['pac_min_mlp']):.3f}–{float(r['pac_max_mlp']):.3f} |"

lines.extend(table_row(r) for r in rows if r["window_ns"] == "20000000")
lines += ["", "## Shorter-window sensitivity (1 ms)", "",
    "These runs stress repeated adaptation. They do not use the paper's 20 ms interval.", "",
    "| Trace | DRAM pages | Frequency ms | PAC ms | PAC reduction | PAC updates | CXL MLP range |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
lines.extend(table_row(r) for r in rows if r["window_ns"] == "1000000")
lines += ["", "## Headroom and migration accounting", "",
    "All-CXL and all-DRAM are references, not alternative frequency/PAC policies.", "",
    "| Trace | Window ms | DRAM pages | All-CXL ms | All-DRAM ms | Frequency promotions | PAC promotions | Frequency migration ms | PAC migration ms |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
for r in rows:
    lines.append(f"| {r['trace']} | {float(r['window_ns'])/1e6:g} | {r['capacity_pages']} | "
        f"{float(r['cxl_ns'])/1e6:.3f} | {float(r['dram_ns'])/1e6:.3f} | "
        f"{r['frequency_promotions']} | {r['pac_promotions']} | "
        f"{float(r['frequency_migration_ns'])/1e6:.3f} | {float(r['pac_migration_ns'])/1e6:.3f} |")
lines += ["", "A single PAC update weights every observed CXL page by the same factor, so",
    "its ordering matches frequency. No-update cases cannot test runtime PAC",
    "adaptation. Multiple updates with varying MLP allow the scores to diverge,",
    "but different placements can still tie or lose on subsequent reuse.", "",
    "Each case passed capacity, load-count conservation, migration-accounting, and",
    "decision-time checks. Every outcome is included in [campaign.csv](campaign.csv)."]
(output / "REPORT.md").write_text("\n".join(lines) + "\n")
print("12 graph comparisons validated; report written.")
