# PACT-inspired PAC results

This experiment uses PACT's windowed MLP/stall-attribution equations with
simulated demand-load occupancy, exact trace samples, and assumed latency
coefficients. It evaluates static placements on held-out instructions; it
does not reproduce PACT's hardware measurements or migration policies.

See [PACT_MODEL.md](../../PACT_MODEL.md) for the equations and limitations.

## Short trace pilot

Each trace uses 200k warmup, 500k training, and 500k evaluation instructions.
The table uses 80 ns DRAM, 250 ns CXL, and 16 memory slots. Positive reduction
means PAC is faster than load-miss-frequency placement.

| Trace | Window | 16 DRAM pages | 64 DRAM pages | 256 DRAM pages |
| --- | ---: | ---: | ---: | ---: |
| 605.mcf_s-1554B | 20 us | +1.844% | -1.331% | +0.072% |
| 605.mcf_s-1554B | 200 us | +1.446% | -1.341% | +0.056% |
| 605.mcf_s-1554B | 20 ms | +0.000% | +0.000% | +0.000% |
| 619.lbm_s-2676B | 20 us | +0.000% | +0.000% | +0.000% |
| 619.lbm_s-2676B | 200 us | +0.000% | +0.000% | +0.000% |
| 619.lbm_s-2676B | 20 ms | +0.000% | +0.000% | +0.000% |
| 623.xalancbmk_s-165B | 20 us | +0.000% | +0.000% | +0.000% |
| 623.xalancbmk_s-165B | 200 us | +0.000% | +0.000% | +0.000% |
| 623.xalancbmk_s-165B | 20 ms | +0.000% | +0.000% | +0.000% |

The paper uses 20 ms. At the default resources, these short training
segments fit into one such window, so PAC is proportional to frequency and
all three traces tie. Shorter windows are sensitivity tests, not the paper's
sampling interval. The full 405-comparison sweep is [campaign.csv](campaign.csv).

## Longer mcf experiment at 20 ms

To exercise the paper's interval, a longer prefix of the same public mcf
trace uses 200k cache warmup, 8 million training instructions, and the next
4 million held-out evaluation instructions. DRAM/CXL latencies remain
80/250 ns, with 16 memory slots and no PAC cooling (alpha=1).

| Training window | Demand-load misses | Observed MLP |
| --- | ---: | ---: |
| 0 | 605969 | 7.576 |
| 1 | 552337 | 7.732 |

| DRAM pages | Frequency runtime (ms) | PAC runtime (ms) | PAC reduction |
| ---: | ---: | ---: | ---: |
| 0 | 19.148196 | 19.148196 | +0.000% |
| 16 | 18.406038 | 18.418595 | -0.068% |
| 64 | 16.076744 | 16.076744 | +0.000% |
| 256 | 13.665154 | 13.650006 | +0.111% |
| 1024 | 6.434403 | 6.434403 | +0.000% |

This run produces small positive and negative differences at the paper's
20 ms interval. It supports testing PAC as a distinct signal, but does not
show a consistent advantage over frequency or reproduce PACT's published
performance claims. Outputs: [long-run results](mcf_long20ms.csv),
[per-window occupancy](mcf_long20ms_pac_windows.csv), and page/placement files.

All zero-capacity and identical-placement controls passed. Every exported
window's page-attribution sum matches its estimated tier stall total. Timing,
cache, format, mixed-tier occupancy, crossing-window accounting, cooling, and
load-only sampling tests also passed.
