# Public trace pilot results

Run on 2026-10-09. These are modeled runtimes from real SPEC instruction traces,
not measured application speedups. See [TRACE_MODEL.md](../TRACE_MODEL.md) for
sources, assumptions, segmentation, score definition, and reproduction.

The default setting uses 80/250 ns fast/slow memory, 16 outstanding-memory
slots, a 1 MiB data cache, and 200k warmup + 500k training + 500k held-out
evaluation instructions. Positive values favor criticality; negative favor frequency.

| Trace | 16 fast pages | 64 fast pages | 256 fast pages |
| --- | ---: | ---: | ---: |
| 605.mcf_s-1554B | +1.594% | -0.710% | +0.336% |
| 619.lbm_s-2676B | +0.000% | +0.000% | +0.085% |
| 623.xalancbmk_s-165B | +0.000% | +0.000% | +0.000% |

Across all 36 nonzero-capacity settings per trace (including capacity saturation):

| Trace | Wins | Losses | Ties | Reduction range |
| --- | ---: | ---: | ---: | ---: |
| 605.mcf_s-1554B | 15 | 5 | 16 | -2.376% to +1.919% |
| 619.lbm_s-2676B | 6 | 0 | 30 | +0.000% to +1.502% |
| 623.xalancbmk_s-165B | 0 | 0 | 36 | +0.000% to +0.000% |

Win/loss threshold is 0.01 percentage points; these are deterministic model
differences, not a statistical significance test. Zero-capacity controls match
all-slow runtime, and identical placements produce identical times.

Conclusion: the slack-based criticality heuristic changes placement and sometimes
improves modeled held-out runtime, particularly in this mcf region. Gains are
small and configuration-dependent; frequency wins in several mcf settings.
This xalancbmk region shows no timing difference. These short prefixes do not
support a general claim that criticality is superior across workloads.

The complete sweep is [campaign.csv](campaign.csv). Per-page profiles and
placement files allow inspection of which pages changed and whether they
were subsequently accessed in the evaluation segment.
