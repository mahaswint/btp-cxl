# Paper-aligned policy comparison on the full available BC-kron region

All six fixed comparisons use the same 999,800,000 measured instructions, 525,613 working-set pages, 262,807 DRAM pages, and 20 ms execution windows. The source is one complete public representative trace member, not the full multithreaded application. Cache and load-domain checks passed.

| Profile | Migration control | Frequency (ms) | PAC (ms) | Runtime reduction | Promotions F/P | Updates F/P |
|---|---|---:|---:|---:|---:|---:|
| legacy | natural | 553.357192 | 553.356815 | +0.000068% | 55/55 | 27/27 |
| legacy | matched | 553.357192 | 553.356815 | +0.000068% | 55/55 | 27/27 |
| paper-all-events | natural | 791.448422 | 774.606837 | +2.127945% | 84154/78197 | 27/27 |
| paper-all-events | matched | 774.653937 | 774.606837 | +0.006080% | 78197/78197 | 27/27 |
| paper-sampled | natural | 564.483715 | 564.493449 | -0.001725% | 3957/3959 | 27/27 |
| paper-sampled | matched | 564.483715 | 564.487811 | -0.000726% | 3957/3957 | 27/27 |

Positive reduction means PAC has a shorter modeled runtime. The matched control uses the smaller natural promotion count as a cap and verifies that both policies actually reach it, with equal demotions. Migration timing and page choices can still differ.

## Execution and copying

| Profile/control | Execution time F/P (ms) | Copy time F/P (ms) | PAC nonempty CXL windows | PAC CXL MLP range |
|---|---:|---:|---:|---:|
| legacy/natural | 553.202136/553.201759 | 0.155056/0.155056 | 24 | 1.280022–1.299753 |
| legacy/matched | 553.202136/553.201759 | 0.155056/0.155056 | 24 | 1.280022–1.299753 |
| paper-all-events/natural | 554.201465/554.153855 | 237.246957/220.452982 | 24 | 1.282504–1.309767 |
| paper-all-events/matched | 554.200955/554.153855 | 220.452982/220.452982 | 24 | 1.282504–1.309767 |
| paper-sampled/natural | 553.328140/553.332236 | 11.155574/11.161213 | 24 | 1.279256–1.299167 |
| paper-sampled/matched | 553.328140/553.332236 | 11.155574/11.155574 | 24 | 1.279256–1.299167 |

Execution time subtraction is a diagnostic, not a zero-migration-cost rerun: placements and drain barriers are those of the charged-copy run. Copies pause execution, unlike PACT's concurrent kernel migration; the larger batch can therefore hurt badly here.

`paper-all-events` means every CXL demand-load miss is observed; it does not mean exact PACT reproduction. `paper-sampled` keeps exact aggregate misses/occupancy but observes every 400th CXL miss for page attribution. It approximates PEBS without hardware filtering or sample loss. Both add 20 bounded bins, access-based reservoir sampling and a 4,096-page per-update cap. The detailed audit lists remaining differences.

No timing coefficients, traces or workload phases were adjusted to obtain a desired speedup. These comparisons do not establish the paper's 18% hardware result.

See [detailed paper audit](../../PAPER_REPRODUCTION.md), [model](../../COMPACT_MODEL.md), [measurements](measurements.json) and [provenance](provenance.json).

Six comparisons completed in 148.42 wall seconds (cached input; preprocessing excluded).
