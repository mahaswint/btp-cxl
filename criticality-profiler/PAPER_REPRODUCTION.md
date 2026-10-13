# PACT reproduction audit for the lightweight C++ profiler

## What the paper asks us to test

PACT estimates slow-tier stalls as `k * LLC_misses / MLP`, attributes them to
sampled pages, and accumulates PAC over 20 ms windows (Algorithm 1). Algorithms
2–3 describe eager demotion and adaptive promotion. Section 5.6 compares PAC
with frequency using comparable migration counts, reporting 18% improvement
and 12–22% across bc-urand, sssp-kron and Silo. High MLP variation matters.
The Figure 9 timelines extend over hundreds of seconds. Its hardware experiment
cannot be reproduced by relabeling one short instruction stream as a full run.
[Paper](https://huaicheng.github.io/p/asplos26-pact.pdf).

The public runtime has subsequently changed: the authors explicitly describe
coroutines, batched migration and Linux 6.3 as improvements beyond the conference
implementation. Its defaults therefore provide a useful reference, rather than
an immutable specification of the exact paper binary.
[Artifact overview](https://github.com/MoatLab/PACT#how-pact-works).

## Trace identity and window coverage

The full available member `bc.kron-5154B.champsimtrace.xz` contains one billion
64-byte instruction records. We exclude 200,000 warmup records and process all
999,800,000 remaining instructions. Its 525,613 observed 4 KiB pages occupy
about 2.005 GiB. DRAM holds 262,807 pages, about 1.003 GiB: a half-footprint split.
The member's download manifest records SHA-256, EOF, XZ integrity and ZIP CRC
checks. No instruction repetition, artificial phase concatenation or slowdown
factor is used. This is a complete member of a representative region from the
[public GAP trace collection](https://zenodo.org/records/20043527), rather than
every region or thread of the source application.

The previous compact comparison completed **27 updates** with a 20 ms execution
interval. Of these, **24** had CXL demand-load misses. Frequency and PAC runtime
were approximately 553.357 ms: about 540 ms before the last observation and
13 ms of remaining execution. These counts are measured from exported decisions,
not inferred from the amount of time the profiler took on the host.

The revised comparisons retain explicit update counts per policy in the
[new report](results/paper_aligned/REPORT.md). Migration pauses are excluded from
the execution observation clock and separately charged to runtime. Consequently,
`runtime / 20 ms` can overcount our actual updates when copies are expensive.
This scheduling convention itself differs from a concurrent sampling runtime.

## Scoring audit

Our replay measures, separately for each tier:

```
area = integral(number of outstanding demand loads dt)
active = integral(number of outstanding demand loads > 0 dt)
MLP = area / active
S = k * aggregate_load_misses / MLP
page_PAC_increment = S * observed_page_samples / observed_tier_samples
```

Stores take service time and resources but do not enter the demand-load counters.
Page samples and counters belong to the same observation window. Sample count
and actual load-miss count are separate; every-400th attribution does not divide
the actual stall total by 400 a second time. Zero observations add no page score.
Cooling defaults to alpha=1. These choices are visible in `RuntimePolicy::update`
and `replay_compact`; exported CSVs include misses, MLP, sample counts and stall
estimates. The artifact's attribution implementation likewise divides its
estimated stalls by the observed per-tier sample population.
[Pinned attribution source](calibration/pact/src/pebs-aggregator.c).

The existing hardware calibration uses 96 real counter rows and reproduces
rounded effective stall constants 238/771 cycles. It is independent evidence
about the scoring relationship. It supplies neither a complete instruction
timeline nor exact per-request latency. We convert score coefficients at an
assumed 2.2 GHz while service latencies remain 90/190 ns. See the
[calibration audit](calibration/pact/REPORT.md) for held-out error.

Our own algebra explains a near tie without requiring a broken implementation:

```
PAC[p] = sum_windows(weight[window] * page_count[p,window])
weight[window] = k / MLP[window]       # all-events observation
```

With constant MLP and no cooling, PAC is a fixed positive multiple of frequency.
It cannot add ranking information. A fixed change to CXL k also cannot create
phase information. The previous BC-kron compact run's nonempty-window CXL MLP
range was only 1.280022–1.299753, a 1.54% span relative to its minimum. This is
a property of this trace *under our execution approximation*, not a measurement
of BC-kron on hardware. Large scores or more recorded instructions alone do not
guarantee a useful variation in the weighting signal.

## Promotion and sampling changes implemented

The old profile remains selectable as `legacy`, so its results remain reviewable.
Two new profiles share the same execution engine and trace:

| Setting | Legacy | paper-all-events | paper-sampled |
|---|---:|---:|---:|
| Update execution interval | 20 ms | 20 ms | 20 ms |
| Slow-tier page observation period | 1 | 1 | 400 |
| Bins | unbounded numeric indices | 20 bounded bins | 20 bounded bins |
| Width reservoir | 100 current slow-page scores | 100 access-updated scores | 100 access-updated scores |
| Promotion batch cap | 64 pages | 4,096 pages | 4,096 pages |
| Pressure threshold | 20 (assumed) | 0.7 | 0.7 |
| Total matched budget | measured per profile | measured per profile | measured per profile |

The bounded histogram lets several high scores occupy the last bucket, even
when one extreme outlier exists. The persistent reservoir samples score updates
at access granularity, rather than refreshing a uniform sample of pages on each
decision. The new sample period preserves aggregate counters while limiting
page attribution to every 400th CXL demand-load miss. It is a deterministic
sampling approximation; PEBS filtering, skid, per-core phase and lost samples
are not modeled.

The defaults and implementation were inspected from a pinned public artifact,
with per-file hashes in [manifest.json](calibration/pact/manifest.json).
[Default settings](calibration/pact/src/config.h) establish the 20 bins,
400-event sampling period and 4,096-page cap;
[binning.c](calibration/pact/src/binning.c) establishes the 0.7 pressure threshold.
`paper-all-events` means complete page observations, **not exact PACT timing**.

## Differences that remain explicit

| Component | This lightweight model | Inspected artifact |
|---|---|---|
| Promotion threshold | Highest occupied bounded bin at each update | Fixed final-bin threshold tested as samples arrive |
| Candidate eligibility | Any tracked CXL page in the selected bin | Queue gate applied to a sampled page's updated score |
| Candidate ordering | Score then page ID, limited to a batch | FIFO migration ring with an in-flight gate |
| Width sample | Same 100-entry access reservoir concept; interpolated quartiles | Integer-rank quartiles; different PRNG |
| Zero interquartile range | Maximum score / bin count, preserving scale invariance | Retain previous width; initial width 1,000 score cycles |
| Pressure denominator | Eligible candidates in current batch selection | Actual migration-ring occupancy |
| Tier updates | Accumulate slow-tier page scores | Also maintains fast-tier metadata and samples |
| Demotion | Least-recently-observed miss pages, immediate capacity swaps | Kernel LRU, cumulative promotion/demotion balance |
| Copy scheduling | Drain requests and pause execution; cost 1,409.6 ns per page | Migration worker and kernel operate alongside application |
| CPU/cache | One stream, one 1 MiB cache, weighted edges and 192-instruction epoch fences | Application threads and real cache/core behavior |
| Memory contention | Fixed service times and 16 outstanding request slots | Actual queues, channels and competing copy traffic |

The artifact behavior in this table is established by the locally pinned
[pact.c](calibration/pact/src/pact.c),
[binning.c](calibration/pact/src/binning.c) and
[balance.c](calibration/pact/src/balance.c). These are significant differences.
In particular, increasing our promotion cap can increase synchronous-copy
penalties substantially. Its observed runtime effect must not be interpreted as
an equivalent change to PACT's real migration worker.

The memory graph is a fast approximation, not an exact contraction of the old
CPU scheduler: conservative fences discard pipelining between epochs. Exact
miss counts and page footprint survive preprocessing, but execution time and
MLP can change. There is no cache coherence, hardware prefetcher or global
multithreaded critical path. Those omissions limit the inference we can draw
from the absence of a gain as well as from a positive result.

## Fair comparison and validation

`run_paper_comparison.py` runs natural and matched comparisons for all three
fixed profiles, using the existing compact cache. It imposes a one-hour cap,
writes progress locally, and generates the report without a monitoring loop.
For matching, both policies receive the smaller natural promotion count; the
runner verifies equal **actual** promotions and demotions, not only equal caps.
It retains unsuccessful and negative outcomes and separates copy charges from
execution time. A matched total still permits different migration times.

The C++ checks cover serial and parallel analytical timing, cache and footprint
conservation, dependency causality, stores, capacity and copy charges. New checks
exercise saturated bins, attribution from sparse samples and a four-window
bounded-policy constant-cost control. The control must produce the same
placement for PAC and frequency; a contrasting varying-overlap fixture must
select different pages. The run verifies full input count and conservation of
all 4,112,395 demand-load misses for every policy.

The appropriate next data target is a chronological multi-phase capture of a
complete bc-urand, sssp-kron or Silo run. Separate representative regions with
weights cannot reconstruct their original timestamps or memory state at phase
boundaries. As a separate experiment, the highest-weight public sssp-kron member
`sssp.kron-246B.champsimtrace.xz` was identified in advance (weight 0.852518),
but it has not been processed in this comparison. It must not be described as
an already tested full-application result.

To improve fidelity without returning to instruction scheduling, a further
extension can schedule asynchronous copy completion events and share bandwidth
with demand requests. That needs an explicitly measured bandwidth/copy model
and a new calibration; simply deleting migration costs would make the outcome
less defensible. Exact reproduction of the hardware percentage ultimately
requires the hardware experiment or an independently validated execution model.

## Completed experiment and interpretation

All six fixed cases completed in 148.42 wall seconds using the existing cache.
Every case completed 27 updates, with 24 nonempty CXL windows. The previous
profile retained its 0.000068% PAC reduction. With the new bounded policy and
complete observations, the natural gain was 2.127945%, but the policies made
84,154 versus 78,197 promotions. At equal actual counts of 78,197 promotions
and demotions each, that gain fell to 0.006080%. The sampled profile's matched
result was -0.000726% with 3,957 promotions and demotions each.

The two matched new-profile results are effectively ties for this model and
trace. The 2.1% natural result mainly reflects fewer charged copies. It is not
evidence of the paper's stronger claim about selecting better pages at equal
migration counts. The revised policy does not compensate for the limited
phase coverage or the simplified execution/migration model. See the
[full comparison report](results/paper_aligned/REPORT.md) for runtimes, copy
charges and measured MLP ranges; all checks described above passed.

## Re-run

From `criticality-profiler`:

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic compact_profiler.cpp -o compact_profiler.exe
g++ -std=c++17 -O2 -Wall -Wextra -pedantic test_compact_profiler.cpp -o test_compact_profiler.exe
./test_compact_profiler.exe
python run_paper_comparison.py
```

This is replay-only: it does not re-download or recompile the billion raw
instructions. The compact cache and its existing checksum metadata are required.
