# Criticality versus frequency: analytical C++ profiler

**Evaluation demonstration:** [Designed variable-MLP streams](SYNTHETIC_STREAMS.md)
show how PAC distinguishes frequent overlapping loads from serial loads. The
[results](results/synthetic_streams/REPORT.md) retain constant-MLP controls and
equal actual migration counts. These are synthetic mechanism experiments.

**Paper comparison:** [Detailed PACT audit](PAPER_REPRODUCTION.md) maps the
paper and pinned artifact to the lightweight implementation. Three fixed policy
profiles are tested with natural and matched migration counts in the
[latest report](results/paper_aligned/REPORT.md).

**Fast comparison:** [Compact memory-event model](COMPACT_MODEL.md) preprocesses
the raw trace once and reuses a small event cache for PAC/frequency comparisons.
It uses coarse compute epochs; its absolute timing is not interchangeable with
the original instruction engine.

**Hardware evidence:** [PACT calibration audit](calibration/pact/REPORT.md)
fits the authors' public counter data. `run_pact_reference.py` applies a sourced,
approximate 90/190 ns tier scenario; exact per-request timings are unavailable
in the inspected artifacts. Existing defaults and experiment results are preserved.

**Workload extension:** [Public GAP graph traces](GRAPH_WORKLOADS.md) add
betweenness centrality and triangle-counting cases closer to PACT's evaluation.

**Runtime extension:** [Dynamic PAC policies](DYNAMIC_MODEL.md) now support
continuous score updates, adaptive promotion, LRU demotion, and migration costs.

**Current default:** [PACT-inspired PAC scoring](PACT_MODEL.md), with time-windowed
per-tier occupancy/MLP and page stall attribution. It is an offline scoring
comparison, not a reproduction of PACT's full online migration runtime.

For the **real public SPEC trace experiment**, see [TRACE_MODEL.md](TRACE_MODEL.md).
It adds a ChampSim reader, register dependencies, cache filtering, resource
constraints, held-out evaluation, and a reproducible parameter sweep. The
phase/lane executable described below remains the synthetic demonstration.

This standalone tool tests whether ranking pages by their contribution to runtime
changes placement outcomes compared with ranking by access count. It assumes
memory latencies and evaluates a dependency/overlap description; it does not
simulate CPU cycles or collect live application traces.

## Build and run

From this directory, with a C++17 compiler:

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic main.cpp -o profiler.exe
./profiler.exe --demo
./profiler.exe --trace example.csv --capacity 1 --fast-ns 10 --slow-ns 100
```

On Linux, use `-o profiler` and `./profiler`. CMake is also supported.
The executable defaults to the three demos when invoked without arguments.
Demo capacities are fixed at one, one, and two pages respectively; `--capacity`
applies to CSV evaluation. Latency options apply to both demos and CSV input.

## Model and criticality definition

All pages are equal size. Fast-memory capacity is a number of pages. Placement
is static for an entire evaluation, with no migration cost. Phases execute
sequentially. Independent lanes within each phase overlap perfectly, and the
phase completes when its longest lane finishes. Within each lane, compute and
dependent memory accesses execute sequentially:

```
lane time = sum(compute_ns + accesses * page_latency)
runtime = sum_over_phases(max_over_lanes(lane time))
frequency(page) = total accesses to page in the training trace
criticality(page) = all_slow_runtime - runtime_with_only_this_page_fast
```

Both policies choose the same number of pages. Criticality ties use frequency,
then page name; frequency ties use page name. Criticality is a **counterfactual
offline score**, computed by replaying the assumed model once per page. It is
not a hardware-observable online signal or a measured stall counter. Profiling
cost scales with the number of distinct pages times the trace evaluation cost.

## CSV input

The header is `phase,lane,page,accesses,compute_ns`. Names cannot contain commas;
quoted CSV fields are unsupported. Access counts must be nonnegative integers;
compute times must be finite and nonnegative. Blank lines and lines beginning
with `#` are ignored. A zero-access row can represent pure compute; its page
label is not ranked unless another row accesses that page.

Rows sharing a phase and lane add together. Phase names identify distinct
barrier-separated regions. Since phases simply add, their naming/order does
not affect runtime. Encode overlap explicitly with different lanes; putting
all accesses in one lane makes criticality proportional to frequency.

Optionally train placement on one trace and evaluate it on another:

```powershell
./profiler.exe --trace training.csv --eval heldout.csv --capacity 16 --fast-ns 80 --slow-ns 250
```

Page identifiers must refer to the same pages across both traces. Previously
unseen evaluation pages stay in slow memory. Without `--eval`, scores and
runtime use the same trace, an optimistic offline comparison.

## Default demonstration results

With assumed fast/slow latencies of 10/100 ns:

| Scenario | Frequency runtime | Criticality runtime | Reduction vs frequency |
| --- | ---: | ---: | ---: |
| Hot accesses overlap a longer compute lane | 2400 ns | 2040 ns | 15% |
| All memory accesses are serial | 500 ns | 500 ns | 0% |
| Two tied bottleneck lanes need joint promotion | 460 ns | 640 ns | -39.13% |

In the first case the hot page has ten accesses but promoting it does not
shorten the compute-bound phase. A page with four exposed accesses saves
360 ns instead. The serial control shows that criticality adds no information
when every access exposes its entire latency. The final case shows that isolated
page scores miss joint benefits: neither tied lane improves phase time alone,
but promoting both does. Criticality ranking is therefore not always optimal.

These examples establish a mechanism and a counterexample, **not a performance
claim about real workloads or CXL hardware**. To test your workloads, supply
their access counts and dependency/overlap structure, evaluate held-out phases
or runs, and sweep fast capacity and assumed latencies. Counts alone cannot
establish criticality. The model omits caches, contention, bandwidth limits,
out-of-order execution, migration, and dynamic changes in scheduling.
