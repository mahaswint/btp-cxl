# Public GAP graph-workload results

Real public bc-kron, bc-twitter, and tc-twitter instruction traces, evaluated
using the existing dynamic PAC/frequency model. Each run has 200k warmup plus
12 million runtime instructions. All cases were chosen before measuring outcomes.
Regions selected by earliest available instruction label.

Sources, selected regions, reproduction, and limitations are in
[GRAPH_WORKLOADS.md](../../GRAPH_WORKLOADS.md). Results are modeled, not hardware
measurements or reproductions of PACT's reported speedups.

Defaults: 80 ns DRAM, 250 ns CXL, 16 memory slots, 64-page promotion batches,
10 GB/s copy throughput, 1000 ns per-page overhead, no extra eager reserve.

## Paper-size 20 ms sampling windows

Positive reduction means PAC is faster than dynamic frequency.

| Trace | DRAM pages | Frequency ms | PAC ms | PAC reduction | PAC updates | CXL MLP range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bc_bc.kron-2608B | 64 | 19.696 | 19.696 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.kron-2608B | 256 | 19.678 | 19.678 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.kron-2608B | 1024 | 19.615 | 19.615 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.twitter-309B | 64 | 19.216 | 19.216 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.twitter-309B | 256 | 19.209 | 19.209 | +0.000% | 0 | 0.000–0.000 |
| bc_bc.twitter-309B | 1024 | 19.078 | 19.078 | +0.000% | 0 | 0.000–0.000 |
| tc_tc.twitter-34B | 64 | 8.094 | 8.094 | +0.000% | 0 | 0.000–0.000 |
| tc_tc.twitter-34B | 256 | 7.747 | 7.747 | +0.000% | 0 | 0.000–0.000 |
| tc_tc.twitter-34B | 1024 | 7.747 | 7.747 | +0.000% | 0 | 0.000–0.000 |

## Shorter-window sensitivity (1 ms)

These runs stress repeated adaptation. They do not use the paper's 20 ms interval.

| Trace | DRAM pages | Frequency ms | PAC ms | PAC reduction | PAC updates | CXL MLP range |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bc_bc.kron-2608B | 256 | 19.785 | 19.737 | +0.243% | 19 | 3.483–3.571 |
| bc_bc.twitter-309B | 256 | 19.910 | 19.619 | +1.459% | 19 | 9.210–9.755 |
| tc_tc.twitter-34B | 256 | 7.747 | 7.747 | +0.000% | 7 | 0.000–0.000 |

## Headroom and migration accounting

All-CXL and all-DRAM are references, not alternative frequency/PAC policies.

| Trace | Window ms | DRAM pages | All-CXL ms | All-DRAM ms | Frequency promotions | PAC promotions | Frequency migration ms | PAC migration ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| bc_bc.kron-2608B | 20 | 64 | 19.701 | 6.585 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.kron-2608B | 20 | 256 | 19.701 | 6.585 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.kron-2608B | 20 | 1024 | 19.701 | 6.585 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.kron-2608B | 1 | 256 | 19.701 | 6.585 | 38 | 21 | 0.107 | 0.059 |
| bc_bc.twitter-309B | 20 | 64 | 19.220 | 6.633 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.twitter-309B | 20 | 256 | 19.220 | 6.633 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.twitter-309B | 20 | 1024 | 19.220 | 6.633 | 0 | 0 | 0.000 | 0.000 |
| bc_bc.twitter-309B | 1 | 256 | 19.220 | 6.633 | 248 | 145 | 0.699 | 0.409 |
| tc_tc.twitter-34B | 20 | 64 | 8.360 | 7.747 | 0 | 0 | 0.000 | 0.000 |
| tc_tc.twitter-34B | 20 | 256 | 8.360 | 7.747 | 0 | 0 | 0.000 | 0.000 |
| tc_tc.twitter-34B | 20 | 1024 | 8.360 | 7.747 | 0 | 0 | 0.000 | 0.000 |
| tc_tc.twitter-34B | 1 | 256 | 8.360 | 7.747 | 0 | 0 | 0.000 | 0.000 |

A single PAC update weights every observed CXL page by the same factor, so
its ordering matches frequency. No-update cases cannot test runtime PAC
adaptation. Multiple updates with varying MLP allow the scores to diverge,
but different placements can still tie or lose on subsequent reuse.

Each case passed capacity, load-count conservation, migration-accounting, and
decision-time checks. Every outcome is included in [campaign.csv](campaign.csv).
