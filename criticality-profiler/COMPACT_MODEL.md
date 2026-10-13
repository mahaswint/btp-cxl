# Fast, coarse PAC versus frequency comparison

`compact_profiler` replaces the four repeated raw instruction replays with one
preprocessing pass and a reusable binary cache of memory requests, dependency
edges, and compute gaps. The original instruction model remains available.

## Preprocessing

The standard 64-byte ChampSim input is read in large buffers. Cache warmup and
the same 1 MiB, 8-way, 64-byte-line LRU cache are applied once. All accessed
virtual pages, including hits, are counted in that pass; DRAM is half that
footprint by default. The trace is neither repeated nor concatenated.

Register miss provenance and same-line store ordering are tracked within
192-instruction epochs. Pure computation propagates provenance without creating
scheduled instruction nodes. Compute/cache-hit work advances an analytical issue
clock `(core_ns + hit_count * hit_ns) / width`. Memory events carry weighted
compute-gap edges. Provably dominated direct ancestors can be removed; no
frontier is silently truncated.

At an epoch boundary, a zero-service fence joins its memory completions and
remaining compute work. Empty epochs become compute gaps. This deliberately
omits pipelining between epochs. It is a conservative coarse approximation,
not an exact contraction of the old CPU/ROB event engine. The fence nodes are
counted separately from actual demand-load/store miss requests.

The cached x86 little-endian/IEEE-754 format has a version marker and records
cache/core/epoch assumptions, source instruction count, page IDs, event types,
weighted dependencies, and compute tails. The validation runner records source
identity, the original download manifest, compiler identity and cache SHA-256.
Changing those identities invalidates its reusable cache.

## Replay and policies

Only memory/fence nodes are scheduled. Dependencies and a 16-request MLP bound
constrain their issue. Exact simulated outstanding-load occupancy and active
time yield per-tier MLP. Stores take time but do not contribute to demand-load
PAC. A 20 ms update drains in-flight requests, scores CXL pages, selects adaptive
promotion candidates, and demotes least-recently-observed DRAM pages.

Within a chosen policy profile, frequency and PAC retain the same binning, sample seed, batch size,
first-touch placement, demotion and costs. They differ in the scoring signal:
frequency adds CXL load misses; PAC adds `k * page_misses / window_MLP`.
Copy costs pause the analytical execution clock and are added once to runtime.
Drain time is already present in execution time. No scores use future accesses.
The final compute-only tail is charged without additional migration decisions.

Migration defaults remain 10 GB/s plus 1000 ns per moved 4 KiB page. Optional
sampling processing cost remains zero. Service latencies are 90/190 ns, core
timing assumes 2.2 GHz, and fitted 238.003/771.070-cycle coefficients are converted
at that clock. The graph must be rebuilt to lower its service-latency bound.

The full-trace validation runs natural adaptive selection and a matched-budget
control. The control caps both policies at the smaller natural promotion count,
then verifies actual equal promotion and demotion counts. Matching the counts
does not match migration timing. Every outcome is retained.

## Build and run

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic compact_profiler.cpp -o compact_profiler.exe
g++ -std=c++17 -O2 -Wall -Wextra -pedantic test_compact_profiler.cpp -o test_compact_profiler.exe
./test_compact_profiler.exe
python run_compact_validation.py
```

The runner benchmarks 5M instructions before preprocessing the complete already
downloaded kron trace. It then reuses the cache for natural and matched 20 ms
comparisons, with a one-hour execution cap. It writes status, logs, provenance,
benchmark measurements, CSV results, and [REPORT.md](results/compact/REPORT.md)
automatically. No polling loop is needed.

For later parameter experiments, replay the saved cache directly:

```powershell
./compact_profiler.exe --cache traces/graph/kron_full.cpt --out results/compact/another_20ms --window-ns 20000000
```

## Validation boundary

Meaningful checks cover analytical serial/parallel controls, cache-miss and page
footprint conservation, dependency causality, store exclusion, migration costs,
and budget limits. An equal-frequency low/high-MLP fixture verifies differing
PAC selection; its constant-MLP control must tie. Those fixtures establish the
mechanism, not a performance claim about a real application.

The public PACT counter dataset independently supports MLP-weighted scoring:
its fitted coefficients and held-out errors are recorded in the calibration
audit. This model still cannot reproduce the original paper's full
multithreaded/Linux runtime. It uses one recorded region, one cache, coarse
compute epochs, synchronous migration, and exact counters with optional approximate page sampling. Differences
in absolute timing from the original engine must not be presented as a speedup
of the workload; wall-clock profiler acceleration is a separate metric.

## Score decay

`--pac-decay 0.7` retains 70% of every existing PAC score before each new
window's attribution: `PAC = 0.7 * old_PAC + new_contribution`. This is not
an EWMA that multiplies the new contribution by 0.3. Request-free windows
also decay known scores, including pages in DRAM. Historical access-reservoir
values are scaled by the same factor so bin widths use consistent units.
Decay changes scores only; tier changes still require a migration decision.

Frequency accumulation is unchanged by default. `--frequency-decay 0.7`
provides a matched-recency control to isolate MLP weighting from forgetting.
Both factors must be finite and in [0,1]. Omitting the flags preserves previous
behavior, including the instruction model's existing `--alpha` fallback.
The factor is applied per update, so 0.7 at 1 ms forgets faster in wall-model
time than 0.7 at 5 ms. This is an experimental policy modification, not a claim
to reproduce the paper's default cooling configuration.

The variable-overlap experiment screens available real traces using fixed
first-touch placement and no migrations, then compares no decay, PAC-only
0.7 decay, and both-score 0.7 decay on the selected continuous bc-twitter prefix.
Selection metadata and every result are in [the report](results/decay_07/REPORT.md).
No trace looping or phase concatenation is used. The isolated build used here
is `compact_profiler_decay.exe`; rebuilding `compact_profiler` exposes the same
options from its source. Example:

```powershell
./compact_profiler_decay.exe --cache traces/decay_probe_bc_twitter.cpt --out results/decay_07/example --window-ns 1000000 --pac-decay 0.7
```

## Paper-aligned policy profiles

`--policy-profile legacy` preserves the original default. `paper-all-events`
adds 20 bounded bins, a persistent 100-entry access-update reservoir, the
artifact's 0.7 pressure threshold and a 4,096-page promotion cap. `paper-sampled`
also observes every 400th CXL load miss for page attribution. Both still measure
all load misses and outstanding-load occupancy for stall estimation.
`--pebs-period N` can override the page observation period.

These are approximations of the paper's policy, not the complete artifact.
Highest occupied-bin selection, zero-IQR fallback, ordering, demotion and
copy scheduling still differ. The [detailed audit](PAPER_REPRODUCTION.md)
identifies each difference. Profile names refer to page observations; they do
not imply exact hardware latencies or exact PEBS behavior.

Run `python run_paper_comparison.py` to reuse the full compact cache for all
three profiles with natural and verified matched migration counts. Results are
retained in [the comparison report](results/paper_aligned/REPORT.md). Progress
is written to `results/paper_aligned/status.json`; there is no monitoring loop.
