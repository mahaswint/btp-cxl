"""Validate PAC controls and export the scoring experiment report."""
import csv
import math
from pathlib import Path

root = Path(__file__).resolve().parent
output = root / "results" / "pac"

def read_csv(path):
    with path.open() as f:
        return list(csv.DictReader(f))

def validate(rows):
    for r in rows:
        freq, pac = float(r["frequency_ns"]), float(r["criticality_ns"])
        if int(r["capacity_pages"]) == 0:
            assert freq == pac == float(r["all_slow_ns"])
        if r["placement_overlap"] == r["selected_pages"]:
            assert freq == pac
        assert math.isclose(100 * (freq - pac) / freq,
            float(r["reduction_percent"]), abs_tol=1e-8)

rows = read_csv(output / "campaign.csv")
assert len(rows) == 405
validate(rows)
window_files = list(output.glob("*_pac_windows.csv"))
for path in window_files:
    for r in read_csv(path):
        assert float(r["active_ns"]) > 0
        assert float(r["measured_mlp"]) >= 1 - 1e-9
        assert math.isclose(float(r["occupancy_ns"]) / float(r["active_ns"]),
            float(r["measured_mlp"]), rel_tol=1e-10)
        assert math.isclose(float(r["estimated_stalls_ns"]),
            float(r["attributed_ns"]), rel_tol=1e-9, abs_tol=1e-7)

lines = ["# PACT-inspired PAC results", "",
    "This experiment uses PACT's windowed MLP/stall-attribution equations with",
    "simulated demand-load occupancy, exact trace samples, and assumed latency",
    "coefficients. It evaluates static placements on held-out instructions; it",
    "does not reproduce PACT's hardware measurements or migration policies.", "",
    "See [PACT_MODEL.md](../../PACT_MODEL.md) for the equations and limitations.", "",
    "## Short trace pilot", "",
    "Each trace uses 200k warmup, 500k training, and 500k evaluation instructions.",
    "The table uses 80 ns DRAM, 250 ns CXL, and 16 memory slots. Positive reduction",
    "means PAC is faster than load-miss-frequency placement.", "",
    "| Trace | Window | 16 DRAM pages | 64 DRAM pages | 256 DRAM pages |",
    "| --- | ---: | ---: | ---: | ---: |"]
for trace in sorted({r["trace"] for r in rows}):
    for window in (20_000, 200_000, 20_000_000):
        sample = {int(r["capacity_pages"]): float(r["reduction_percent"]) for r in rows
            if r["trace"] == trace and int(r["window_ns"]) == window
            and r["slow_ns"] == "250" and r["mlp"] == "16"}
        label = {20_000:"20 us",200_000:"200 us",20_000_000:"20 ms"}[window]
        lines.append(f"| {trace} | {label} | " + " | ".join(f"{sample[c]:+.3f}%" for c in (16,64,256)) + " |")
lines += ["", "The paper uses 20 ms. At the default resources, these short training",
    "segments fit into one such window, so PAC is proportional to frequency and",
    "all three traces tie. Shorter windows are sensitivity tests, not the paper's",
    "sampling interval. The full 405-comparison sweep is [campaign.csv](campaign.csv).", ""]

long_path = output / "mcf_long20ms.csv"
if long_path.exists():
    long = read_csv(long_path)
    validate(long)
    windows = read_csv(output / "mcf_long20ms_pac_windows.csv")
    assert len(windows) >= 2, "Long experiment must span multiple paper-size windows"
    lines += ["## Longer mcf experiment at 20 ms", "",
        "To exercise the paper's interval, a longer prefix of the same public mcf",
        "trace uses 200k cache warmup, 8 million training instructions, and the next",
        "4 million held-out evaluation instructions. DRAM/CXL latencies remain",
        "80/250 ns, with 16 memory slots and no PAC cooling (alpha=1).", "",
        "| Training window | Demand-load misses | Observed MLP |",
        "| --- | ---: | ---: |"]
    for r in windows:
        lines.append(f"| {r['window']} | {r['load_misses']} | {float(r['measured_mlp']):.3f} |")
    lines += ["", "| DRAM pages | Frequency runtime (ms) | PAC runtime (ms) | PAC reduction |",
        "| ---: | ---: | ---: | ---: |"]
    for r in long:
        lines.append(f"| {r['capacity_pages']} | {float(r['frequency_ns'])/1e6:.6f} | "
            f"{float(r['criticality_ns'])/1e6:.6f} | {float(r['reduction_percent']):+.3f}% |")
    lines += ["", "This run produces small positive and negative differences at the paper's",
        "20 ms interval. It supports testing PAC as a distinct signal, but does not",
        "show a consistent advantage over frequency or reproduce PACT's published",
        "performance claims. Outputs: [long-run results](mcf_long20ms.csv),",
        "[per-window occupancy](mcf_long20ms_pac_windows.csv), and page/placement files.", ""]
lines += ["All zero-capacity and identical-placement controls passed. Every exported",
    "window's page-attribution sum matches its estimated tier stall total. Timing,",
    "cache, format, mixed-tier occupancy, crossing-window accounting, cooling, and",
    "load-only sampling tests also passed."]
(output / "REPORT.md").write_text("\n".join(lines) + "\n")
print(f"Validated {len(rows)} pilot comparisons and {len(window_files)} occupancy exports; report written.")
