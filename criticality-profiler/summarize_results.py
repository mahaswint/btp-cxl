"""Validate sweep controls and generate a concise pilot report."""
import csv
from pathlib import Path

root = Path(__file__).resolve().parent
with (root / "results/campaign.csv").open() as f:
    rows = list(csv.DictReader(f))
assert len(rows) == 135, "Expected three traces, nine model settings, five capacities"
for row in rows:
    if int(row["capacity_pages"]) == 0:
        assert float(row["frequency_ns"]) == float(row["criticality_ns"]) == float(row["all_slow_ns"])
    if int(row["placement_overlap"]) == int(row["selected_pages"]):
        assert float(row["frequency_ns"]) == float(row["criticality_ns"])
    gain = 100 * (float(row["frequency_ns"]) - float(row["criticality_ns"])) / float(row["frequency_ns"])
    assert abs(gain - float(row["reduction_percent"])) < 1e-8

lines = ["# Public trace pilot results", "",
    "Run on 2026-10-09. These are modeled runtimes from real SPEC instruction traces,",
    "not measured application speedups. See [TRACE_MODEL.md](../TRACE_MODEL.md) for",
    "sources, assumptions, segmentation, score definition, and reproduction.", "",
    "The default setting uses 80/250 ns fast/slow memory, 16 outstanding-memory",
    "slots, a 1 MiB data cache, and 200k warmup + 500k training + 500k held-out",
    "evaluation instructions. Positive values favor criticality; negative favor frequency.", "",
    "| Trace | 16 fast pages | 64 fast pages | 256 fast pages |",
    "| --- | ---: | ---: | ---: |"]
traces = sorted({r["trace"] for r in rows})
for trace in traces:
    selected = {int(r["capacity_pages"]): float(r["reduction_percent"]) for r in rows
        if r["trace"] == trace and r["slow_ns"] == "250" and r["mlp"] == "16"}
    lines.append(f"| {trace} | " + " | ".join(f"{selected[c]:+.3f}%" for c in (16,64,256)) + " |")
lines += ["", "Across all 36 nonzero-capacity settings per trace (including capacity saturation):", "",
    "| Trace | Wins | Losses | Ties | Reduction range |",
    "| --- | ---: | ---: | ---: | ---: |"]
for trace in traces:
    gains = [float(r["reduction_percent"]) for r in rows if r["trace"] == trace and r["capacity_pages"] != "0"]
    win = sum(g > .01 for g in gains)
    loss = sum(g < -.01 for g in gains)
    tie = len(gains) - win - loss
    lines.append(f"| {trace} | {win} | {loss} | {tie} | {min(gains):+.3f}% to {max(gains):+.3f}% |")
lines += ["", "Win/loss threshold is 0.01 percentage points; these are deterministic model",
    "differences, not a statistical significance test. Zero-capacity controls match",
    "all-slow runtime, and identical placements produce identical times.", "",
    "Conclusion: the slack-based criticality heuristic changes placement and sometimes",
    "improves modeled held-out runtime, particularly in this mcf region. Gains are",
    "small and configuration-dependent; frequency wins in several mcf settings.",
    "This xalancbmk region shows no timing difference. These short prefixes do not",
    "support a general claim that criticality is superior across workloads.", "",
    "The complete sweep is [campaign.csv](campaign.csv). Per-page profiles and",
    "placement files allow inspection of which pages changed and whether they",
    "were subsequently accessed in the evaluation segment."]
(root / "results/REPORT.md").write_text("\n".join(lines) + "\n")
print("135 comparisons validated; results/REPORT.md written.")
