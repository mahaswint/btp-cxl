# Fast PAC-versus-frequency validation

## Efficiency

5M-instruction benchmark: preprocess 0.659 s, four-policy replay 0.061 s.
Previous instruction-model pilot: 5.837 s. First-run ratio: 8.11x.
Full trace: 999,800,000 measured instructions; compact cache 405.2 MB versus 64.0 GB raw.
Full preprocessing: 108.572 s. Natural comparison: 22.803 s. Matched comparison: 24.506 s.
Subsequent comparisons reuse the compact cache; no raw decoding or cache filtering is repeated.

## Full trace at 20 ms, half-footprint DRAM

Positive reduction favors PAC. Natural and matched results are both retained.

| Comparison | Frequency modeled ms | PAC modeled ms | PAC reduction | Frequency/PAC promotions | Frequency/PAC copy ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| natural | 553.357192 | 553.356815 | +0.000068% | 55/55 | 0.155056/0.155056 |
| matched | 553.357192 | 553.356815 | +0.000068% | 55/55 | 0.155056/0.155056 |

Matched promotion budget: 55. Equal actual promotions and demotions were verified.
A zero budget supplies a no-migration control, not evidence about promotion quality.

## What is validated

The original and compact models have exactly equal load-miss counts and accessed-page footprints.
Tests cover serial/parallel analytical timing, cache filtering, causal weighted dependencies, migration
charges, budget limits, and store exclusion. Equal-frequency low/high-MLP samples select different
pages under PAC; the constant-MLP control ties. These controlled tests validate the mechanism,
not an empirical workload speedup.
Published PACT hardware-counter data: miss/stall correlation 0.829;
miss/MLP correlation 0.974, across 96 workloads.
The calibrated CXL stall model's leave-one-out mean absolute error is 39.7%.
This supports the scoring premise while showing that prediction is approximate.

## Limits

Compute and cache-hit work is aggregated into conservative 192-instruction epochs; epoch memory
completions are joined by zero-service fences. Within epochs, register miss provenance and same-line
store ordering are retained. This omits cross-epoch pipelining and uses an analytical issue clock
instead of CPU/ROB scheduling. Absolute timing does not match the instruction engine.
For example, the 5M pilot frequency runtime is 2.760863 ms in the compact model
versus about 2.014 ms in the original engine.
The comparisons are fair within this approximation, but do not reproduce the paper's full
multithreaded/Linux runtime or establish its reported 18% speedup. One representative trace region
is evaluated. Latencies are 90/190 ns; sampling cost is zero and migration remains synchronous.
Natural and matched CSVs include all-CXL/all-DRAM references, copy costs, and demand-load counts.
Saved reports are not substitutes for validating a full PACT deployment.
