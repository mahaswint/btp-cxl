# Unattended longer bc-kron experiment

The requested 15–20 minutes is interpreted as profiler wall time on this PC,
not 15–20 minutes of modeled workload execution. A streaming five-million-
instruction pilot took 5.837 seconds. Eight comparisons target 1050 seconds,
giving 112 million instructions per comparison by linear extrapolation.
Actual duration can differ because later trace phases and policy work differ.
If the public trace ends early, complete available instructions are used and the
shortfall is recorded. No artificial looping, concatenation, or sleeps extend it.
Downloading the longer prefix is separate from profiling time.

Workload: real GAP bc-kron region 5154, the highest published-weight region.
This remains one representative region, not a full multithreaded PACT application.
DRAM capacity is `ceil(0.5 * distinct accessed virtual pages)` in the measured
prefix. Loads/stores and cache-hit pages count; warmup-only pages do not.
This uses working-set metadata to configure capacity, not future accesses to
rank pages. It approximates a 1:1 address-footprint split, not application RSS.

Settings use 90 ns DRAM, 190 ns CXL-emulated memory, 2.2 GHz core timing,
and fitted 238.003/771.070-cycle PAC coefficients converted at 2.2 GHz.
Other settings stay at 1 MiB/8-way cache, 192-entry ROB, 16 outstanding memory
instructions, 64-page batches, zero reserve, 10 GB/s copies plus 1000 ns per move.
The execution remains single-stream with synchronous migration and zero sampling
processing cost. Scaling capacity/latency does not make this a full PACT system.

Four windows (20/5/1/0.2 ms) each have a natural adaptive comparison followed
by a matched-migration control. The control gives each policy the smaller natural
promotion total as a hard budget and checks equal final promotion/demotion counts.
It does not force identical migration timing. A zero budget is labelled accordingly.
All-CXL/all-DRAM references accompany each comparison.

The streaming engine reads instructions on admission and retains only live ROB
dependency state. Trace-order cache outcomes and scoring causality are preserved.
Working-set/policy metadata still scale with distinct pages. Equivalence tests
cover ROB wrap, register/store dependencies, cache filtering, migration and MLP;
a saved pre-change public-trace run also matches exactly.

Run after building the profiler and creating the pilot measurement:

```powershell
python run_long_bc_kron.py
```

The detached worker automatically writes `results/long_bc_kron/plan.json`,
`status.json`, per-case logs/configurations, `campaign.csv`, and the final
`REPORT.md`. Failures are recorded in status and logs. No monitoring loop is used.
