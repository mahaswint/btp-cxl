# Public GAP graph-workload results

Real public bc-kron, bc-twitter, and tc-twitter instruction traces, evaluated
using the existing dynamic PAC/frequency model. Each run has 200k warmup plus
12 million runtime instructions. All cases were chosen before measuring outcomes.
Regions selected by highest published execution weight.

Sources, selected regions, reproduction, and limitations are in
[GRAPH_WORKLOADS.md](../../GRAPH_WORKLOADS.md). Results are modeled, not hardware
measurements or reproductions of PACT's reported speedups.

Defaults: 80 ns DRAM, 250 ns CXL, 16 memory slots, 64-page promotion batches,
10 GB/s copy throughput, 1000 ns per-page overhead, no extra eager reserve.

## Paper-size 20 ms sampling windows

Positive reduction means PAC is faster than dynamic frequency.

| Trace | DRAM pages | Frequency ms | PAC ms | PAC reduction | PAC updates | CXL MLP range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bc_bc.kron-5154B | 64 | 7.517 | 7.517 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.kron-5154B | 256 | 7.490 | 7.490 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.kron-5154B | 1024 | 7.388 | 7.388 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.twitter-876B | 64 | 20.632 | 20.632 | +0.000% | 1 | 9.809–9.809 |
| bc_bc.twitter-876B | 256 | 20.615 | 20.615 | +0.000% | 1 | 9.788–9.788 |
| bc_bc.twitter-876B | 1024 | 20.532 | 20.532 | +0.000% | 1 | 9.697–9.697 |
| tc_tc.twitter-4460B | 64 | 14.327 | 14.327 | +0.000% | 0 | 0.000–0.000 |
| tc_tc.twitter-4460B | 256 | 14.015 | 14.015 | +0.000% | 0 | 0.000–0.000 |
| tc_tc.twitter-4460B | 1024 | 12.810 | 12.810 | +0.000% | 0 | 0.000–0.000 |

## Shorter-window sensitivity (1 ms)

These runs stress repeated adaptation. They do not use the paper's 20 ms interval.

| Trace | DRAM pages | Frequency ms | PAC ms | PAC reduction | PAC updates | CXL MLP range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bc_bc.kron-5154B | 256 | 7.516 | 7.513 | +0.038% | 7 | 1.823–1.854 |
| bc_bc.twitter-876B | 256 | 20.759 | 20.776 | -0.082% | 20 | 9.342–10.023 |
| tc_tc.twitter-4460B | 256 | 14.150 | 14.167 | -0.120% | 14 | 1.082–1.222 |

## Headroom and migration accounting

All-CXL and all-DRAM are references, not alternative frequency/PAC policies.

| Trace | Window ms | DRAM pages | All-CXL ms | All-DRAM ms | Frequency promotions | PAC promotions | Frequency migration ms | PAC migration ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bc_bc.kron-5154B | 20 | 64 | 7.533 | 2.947 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.kron-5154B | 20 | 256 | 7.533 | 2.947 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.kron-5154B | 20 | 1024 | 7.533 | 2.947 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.kron-5154B | 1 | 256 | 7.533 | 2.947 | 9 | 8 | 0.025 | 0.023 |
| bc_bc.twitter-876B | 20 | 64 | 20.635 | 7.029 | 1 | 1 | 0.003 | 0.003 |
| bc_bc.twitter-876B | 20 | 256 | 20.635 | 7.029 | 1 | 1 | 0.003 | 0.003 |
| bc_bc.twitter-876B | 20 | 1024 | 20.635 | 7.029 | 1 | 1 | 0.003 | 0.003 |
| bc_bc.twitter-876B | 1 | 256 | 20.635 | 7.029 | 52 | 58 | 0.147 | 0.164 |
| tc_tc.twitter-4460B | 20 | 64 | 14.451 | 4.736 | 0 | 0 | 0.000 | 0.000 |
| tc_tc.twitter-4460B | 20 | 256 | 14.451 | 4.736 | 0 | 0 | 0.000 | 0.000 |
| tc_tc.twitter-4460B | 20 | 1024 | 14.451 | 4.736 | 0 | 0 | 0.000 | 0.000 |
| tc_tc.twitter-4460B | 1 | 256 | 14.451 | 4.736 | 46 | 52 | 0.130 | 0.147 |

A single PAC update weights every observed CXL page by the same factor, so
its ordering matches frequency. No-update cases cannot test runtime PAC
adaptation. Multiple updates with varying MLP allow the scores to diverge,
but different placements can still tie or lose on subsequent reuse.

Each case passed capacity, load-count conservation, migration-accounting, and
decision-time checks. Every outcome is included in [campaign.csv](campaign.csv).
