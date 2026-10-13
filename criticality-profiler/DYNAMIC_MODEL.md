# Dynamic PACT-inspired runtime

`dynamic_profiler` adds continuous PAC updates, adaptive-bin promotion, cold-page
demotion, eager free-space reservation, and explicit migration costs. It compares
PAC with dynamic frequency using the same mechanisms and costs. The static
profiler and previous experiment outputs remain available separately.

Policy source: [PACT paper, sections 4.3–4.5](https://huaicheng.github.io/p/asplos26-pact.pdf).
This is an analytical implementation of those ideas, not the authors' kernel or
userspace runtime. The departures below matter when interpreting its results.

## Execution and causality

After cache warmup, one continuous instruction segment executes. There is no
training/evaluation split or prescient initial ranking. Both managed policies
start identically: previously unseen pages fill available DRAM on first cache
miss until capacity is full; later new pages start in CXL. Initial first-touch
allocation costs zero, whereas subsequent tier changes incur migration cost.

The new execution engine schedules instruction admission, operand readiness,
completion, and policy events. Register and same-line store dependencies persist
across sampling and migration points. In-order admission/retirement enforces the
instruction window, and ready instructions compete for outstanding memory
slots. Unlike the earlier static evaluator's instruction-order slot reservation,
this engine starts dependency-ready work when resources become available.
All-CXL, all-DRAM, frequency, and PAC use this same engine. Their runtimes should
not be directly compared to results from the previous engine.

Cache hits/misses are still precomputed in trace operand order using the shared
single simplified cache. The complete trace is loaded to construct dependencies,
but policy scores use only issued requests observed by the current sample time.
No score reads future accesses. Recency uses observed cache-miss instruction
issues (loads and stores); cache-hit page recency is unavailable in this model.
This is a sampled LRU approximation, not the kernel's MG-LRU implementation.

For longer traces, `--streaming 1` computes the same cache outcomes at instruction
admission and retains only live ROB dependencies. The full-load path remains
available. Both paths use the same bounded scheduler and passed exact equivalence
checks. `--capacity-fraction 0.5` additionally scans the measured prefix to size
DRAM from distinct accessed pages, without using future accesses for scores.
`--promotion-budget N` bounds each managed policy's total promotions; the long
campaign verifies actual matched counts. See [LONG_RUN.md](LONG_RUN.md).

## Sampling and score updates

Default sampling period is 20 ms. At a deadline, admission and new execution
pause while already executing instructions drain. The actual counter window
ends at the drain completion, typically slightly later than the deadline.
Request intervals beyond that observation time never enter the counters.
Per-tier occupancy and active time are measured from demand-load miss intervals.

```
MLP[t] = integral(outstanding requests to tier t) / active time of tier t
slow_stalls = k_cxl * slow_load_misses / MLP_cxl
PAC[p] = alpha * PAC[p] + slow_stalls * page_slow_misses / slow_load_misses
Frequency[p] = alpha * Frequency[p] + page_slow_misses
```

Both scores observe slow-tier load misses, with exact counts instead of PEBS
sampling. Alpha defaults to 1, as in the paper. DRAM/CXL k coefficients default
to assumed latency and can be overridden; they are not hardware-calibrated.
Mixed-tier occupancy is exported for inspection, but only CXL samples add scores.
Pages in DRAM retain historical scores for later use if demoted.

## Adaptive promotion

At each update, the policy forms a deterministic reservoir sample of up to 100
current positive-score CXL pages. It computes quartiles and a Freedman–Diaconis
bin width: `2 * (Q3-Q1) / cbrt(number of eligible pages)`. It applies the paper's
one-step double/halve scaling using an explicitly assumed candidate-ratio
threshold of 20, then selects pages in the highest occupied bin.

Zero IQR falls back to max-score/20 (with a positive numerical floor). These
tie/fallback details and threshold are model choices, not a claim to match all
details of PACT's runtime artifact. Candidates within the top bin are ordered by
score then page ID, and limited to a configurable promotion batch (default 64).
Reservoir sampling uses a reproducible seed (default 1).

The dynamic frequency comparison uses identical adaptive binning, demotion,
batch limits, and cost parameters. It isolates the scoring signal; it is not a
reimplementation of TPP, Colloid, or any other published baseline.

## Eager demotion and migration cost

Before promoting a batch, least-recently-observed DRAM pages are demoted to make
space. `--reserve N` additionally creates N free DRAM slots for future promotions
(default 0). Promotions are limited so occupancy plus the reserve fits capacity.
Every demotion and promotion is logged and separately charged:

```
cost_per_move_ns = move_overhead_ns + 4096 / migration_gbps
```

Defaults assume 10 GB/s copy throughput and 1000 ns overhead per moved page,
which gives 1409.6 ns per move. Swapping a page costs two moves. Optional sampling
processing cost defaults to zero. These are adjustable assumptions, not measured
Linux migration costs.

Migrations are synchronous: all executing instructions drain, then the workload
pauses for serialized page copies and sampling overhead. Queued/dependent work
resumes afterward with its dependencies intact and the new page tiers. No page
moves while it has an outstanding request. The next sampling deadline is one
period after resumption, so drain and migration extend wall-clock spacing.
This conservative model does not reproduce PACT's overlapping background
migration or shared-link contention. Drain time is exported separately; it is
already part of execution time, not a second additive copy charge.

Zero DRAM capacity disables policy events and matches all-CXL execution.
`--batch 0 --reserve 0` disables policy events and leaves first-touch placement
fixed. There are no migration decisions after the final instruction completes.

## Build, run, and inspect

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic dynamic_profiler.cpp -o dynamic_profiler.exe
g++ -std=c++17 -O2 -Wall -Wextra -pedantic test_dynamic_profiler.cpp -o test_dynamic_profiler.exe
./test_dynamic_profiler.exe
python run_dynamic_campaign.py
python summarize_dynamic_results.py
```

Use the existing trace download scripts first. The longer mcf prefix is fetched
with the command in [PACT_MODEL.md](PACT_MODEL.md). `run_dynamic_campaign.py`
uses the documented 20 ms long run and explicitly labeled shorter-window stress
tests; shorter periods are not the paper's sampling configuration.

Each case writes a summary for all-CXL, all-DRAM, dynamic frequency, and PAC,
full model parameters, per-decision statistics for both policies, all page moves,
and final DRAM pages. Migration counts, migration stall, and tier demand-load
counts are included. [Results](results/dynamic/REPORT.md) compare the policies
without presuming that PAC will win.
