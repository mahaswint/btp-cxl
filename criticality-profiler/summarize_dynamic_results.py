"""Check runtime accounting and report all documented dynamic cases."""
import csv
import math
from pathlib import Path

root = Path(__file__).resolve().parent
output = root / "results" / "dynamic"
cases = ["pilot", "mcf_long20ms", "mcf_long1ms_reserve8", "lbm_short200us", "xalancbmk_short200us"]

def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))

lines = ["# Dynamic tiering results", "",
    "PAC now updates during execution and controls adaptive-bin promotions and",
    "LRU demotions. Both managed policies pay the same assumed page-copy cost.",
    "The frequency comparison uses the same adaptive policy with miss counts.", "",
    "See [DYNAMIC_MODEL.md](../../DYNAMIC_MODEL.md) for the model, assumptions,",
    "reproduction, and differences from the PACT implementation.", "",
    "All cases assume 80 ns DRAM, 250 ns CXL, 16 outstanding-memory slots,",
    "10 GB/s migration throughput, and 1000 ns fixed overhead per moved page.",
    "Copies pause the workload; this is not background Linux migration.", "",
    "| Case | All-CXL ms | All-DRAM ms | Frequency ms | PAC ms | PAC reduction | PAC promotions/demotions |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
for case in cases:
    path = output / (case + ".csv")
    rows = {r["policy"]: r for r in read(path)}
    assert set(rows) == {"cxl", "dram", "frequency", "pac"}
    config = dict(line.strip().split("=", 1) for line in (output / (case + "_config.txt")).read_text().splitlines())
    cost = float(config["move_overhead_ns"]) + 4096 / float(config["migration_gbps"])
    load_total = int(rows["cxl"]["cxl_loads"])
    for mode, row in rows.items():
        assert int(row["dram_loads"]) + int(row["cxl_loads"]) == load_total
        if mode in ("cxl", "dram"):
            assert int(row["promotions"]) == int(row["demotions"]) == int(row["decisions"]) == 0
            continue
        windows = read(output / f"{case}_{mode}_windows.csv")
        moves = read(output / f"{case}_{mode}_moves.csv")
        assert len(windows) == int(row["decisions"])
        assert sum(m["direction"] == "CXL_to_DRAM" for m in moves) == int(row["promotions"])
        assert sum(m["direction"] == "DRAM_to_CXL" for m in moves) == int(row["demotions"])
        assert math.isclose(len(moves) * cost, float(row["migration_ns"]), abs_tol=1e-5, rel_tol=1e-10)
        assert math.isclose(sum(float(w["migration_ns"]) for w in windows), float(row["migration_ns"]), abs_tol=1e-5)
        previous = -1
        for window in windows:
            assert float(window["sample_ns"]) > previous
            assert int(window["dram_pages"]) <= int(config["capacity"]) - int(config["reserve"])
            assert float(window["resume_ns"]) >= float(window["sample_ns"])
            assert float(window["resume_ns"]) <= float(row["runtime_ns"])
            assert math.isclose(float(window["resume_ns"]) - float(window["sample_ns"]),
                float(window["migration_ns"]) + float(config["sampling_cost_ns"]), abs_tol=1e-5)
            previous = float(window["resume_ns"])
    f, p = float(rows["frequency"]["runtime_ns"]), float(rows["pac"]["runtime_ns"])
    times = [float(rows[m]["runtime_ns"]) / 1e6 for m in ("cxl", "dram", "frequency", "pac")]
    lines.append(f"| {case} | " + " | ".join(f"{t:.3f}" for t in times)
        + f" | {100*(f-p)/f:+.3f}% | {rows['pac']['promotions']}/{rows['pac']['demotions']} |")

lines += ["", "The long runs use 12 million instructions following 200k cache-warmup",
    "instructions. Other runs use 1 million instructions following the same warmup.",
    "The 20 ms long run uses 256 DRAM pages with no extra reserve. The 1 ms long",
    "stress run uses 256 DRAM pages and an 8-page eager reserve. Short runs use",
    "64 DRAM pages and 200 us windows. Shorter windows are sensitivity tests,",
    "not the paper's default sampling interval.", "",
    "The 20 ms run ties because both policies choose the same first promotion",
    "batch and the workload finishes before the next update. Faster sampling",
    "exercises repeated runtime adaptation and exposes migration churn.", "",
    "A positive comparison against dynamic frequency does not necessarily mean",
    "tiering beats leaving the workload on CXL. In particular, inspect the lbm",
    "stress case against its all-CXL reference: less churn helps PAC relative to",
    "frequency, while migration still costs more than placement saves.", "",
    "Migration accounting, capacity/reserve bounds, tier-load conservation, and",
    "decision timestamps were validated. Unit tests cover dependencies, causal",
    "sampling, repeated updates, adaptive bins, cold-page selection, migration",
    "costs, disabled migrations, and zero-capacity controls."]
(output / "REPORT.md").write_text("\n".join(lines) + "\n")
print("Dynamic result accounting validated; report written.")
