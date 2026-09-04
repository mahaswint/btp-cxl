# Native BTP study versus successful SimCXL runs — 4 September 2026

**Finding: these results expose modeled CXL latency, but cannot establish a native-versus-CXL performance penalty.** Input sizes, CPU model, caches, concurrency, software environment and timing boundaries differ. No matched local-memory simulator baseline is present in the inspected result set.

Four workloads completed: memory_pilot, STREAM, pointer_chase and ANN. Pointer chase is included using its recovered report; its original suite status was a reporting failure, not a failed guest workload. BERT, kmeans, DLRM and llama_cpp have no completed results in the inspected trial/recovery summaries and are excluded. A saved “running” status does not establish that a process is currently alive.

Native application results below use one consistent perf group (stdout_core_cache.log) across five successful campaign repetitions. They are means of five reported results, not a pool of all six profiler-group executions. Native memory_pilot has three exploratory folders and only a checksum in its application output. Simulator results are one smoke run each.

| Workload | Native input | Simulator input | Application observation |
|---|---|---|---|
| memory_pilot | 512 MiB, 8 passes | 1 MiB, 8 passes | Both emit a checksum; no comparable application timer |
| STREAM | 50,000,000 doubles/array × 3 = 1.2 GB; 20 iterations; 8 threads | 65,536 doubles/array × 3 = 1.5 MiB; 3 iterations; 1 thread | Simulator timer too coarse for valid kernel bandwidth |
| pointer_chase | 512 MiB; requested n=5; 500 ms sampling interval; 1 worker | 2 MiB; requested n=1; 10 ms sampling interval; 1 worker | Different cache and sampling regimes |
| ANN | 200,000 vectors × 128 dimensions; 1,000 queries; top-10 | 1,024 vectors × 128 dimensions; 8 queries; top-10 | Same HNSW driver algorithm/settings, different database and concurrency |

Native machine: i7-12700, 25 MiB L3. Simulator: one TimingSimpleCPU, approximately 2.4 GHz, 2 MiB L2 and 96 MiB L3, 8 GiB CXL endpoint, node-1 allocation. Native ANN is permitted CPUs 0–15; its campaign command does not explicitly fix its OpenMP thread count. Do not assume it ran with exactly eight threads.

| Application metric | Native mean ± sample SD (5 reps) | Simulator output | Interpretation |
|---|---:|---:|---|
| STREAM Copy GB/s | 21.6074 ± 0.0212 | inf | Reject simulator kernel rate: ~1 ms timer resolution |
| STREAM Scale GB/s | 21.4121 ± 0.0322 | 1.0487 | Reject simulator kernel rate: ~1 ms timer resolution |
| STREAM Add GB/s | 21.7196 ± 0.0421 | inf | Reject simulator kernel rate: ~1 ms timer resolution |
| STREAM Triad GB/s | 21.7084 ± 0.0376 | 1.5745 | Reject simulator kernel rate: ~1 ms timer resolution |
| Pointer dereference ns | 60.9222 ± 0.0369 | 7.437 | Not CXL transaction latency; cache hits and timing/sampling affect it |
| ANN queries/s | 72039.23 ± 1966.51 | 2,667.0721 | Apparent 27.01× throughput gap, **not attributable to CXL** |
| ANN BUILD_TIME_SEC | 22.797356 ± 1.155323 | 0.290956 | Different amounts of work; guest search lasts only ~3 ms |
| ANN SEARCH_TIME_SEC | 0.013890 ± 0.000391 | 0.003000 | Different amounts of work; guest search lasts only ~3 ms |

The 7.437 ns pointer result is not evidence that CXL beats native DRAM. It is much shorter than the ~300 ns observed CXL reads and uses a 2 MiB buffer. Cache-resident chasing can coexist with CXL traffic from allocation, initialization and other activity in the process-wide phase. The existing markers do not isolate the chase loop.

**CXL measurements, scoped to the completed workload phase.** Latency runs from the host-facing CXL boundary to its returning response, excluding CPU/cache lookup time. Tick frequency is 10¹² Hz, so 1,000 ticks = 1 ns. Bandwidth is transferred CXL payload divided by simulated phase time; it is not STREAM algorithmic bandwidth.

| Workload | Phase seconds | Read requests | Read MiB | Mean GB/s | Mean ns | P50 ns | P95 ns | P99 ns |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| memory_pilot | 0.017326 | 19,723 | 1.204 | 0.07285 | 301.33 | 296.90 | 442.44 | 631.34 |
| stream | 0.045628 | 29,987 | 1.830 | 0.04206 | 296.82 | 293.57 | 406.16 | 597.54 |
| pointer_chase | 1.222474 | 1,107,339 | 67.587 | 0.05797 | 300.40 | 300.24 | 424.09 | 605.48 |
| ann | 0.366232 | 93,627 | 5.715 | 0.01636 | 290.05 | 281.48 | 397.76 | 607.57 |

All four phases record zero CXL writes. This does not mean the applications performed no stores: stores may stay in caches and writebacks can occur outside the phase. These runs do not characterize write throughput or bidirectional performance.

| Workload | Fabric ns | Device enqueue-to-start ns | Device service ns | Return ns | Non-service share of mean |
|---|---:|---:|---:|---:|---:|
| memory_pilot | 68.04 | 16.33 | 135.65 | 81.32 | 55.0% |
| stream | 67.56 | 16.32 | 131.62 | 81.32 | 55.7% |
| pointer_chase | 67.81 | 16.33 | 134.95 | 81.32 | 55.1% |
| ann | 66.66 | 16.31 | 125.76 | 81.32 | 56.6% |

Fabric plus return contributes about 148–149 ns per read; all non-service components contribute about 165 ns. This is modeled path cost, **not an incremental penalty relative to native DRAM**: the local path also has latency, and no matched measurement exists. Device service includes backend scheduling. The ~16 ns enqueue-to-start component includes modeled protocol/scheduling delay, so it is not all saturation-induced waiting. Component means sum to total; individual percentiles need not sum.

| Workload | Endpoint queue-full events | Endpoint backpressure cycles | Mean endpoint request depth | P99 depth | Max depth | Modeled upstream port read utilization |
|---|---:|---:|---:|---:|---:|---:|
| memory_pilot | 1,483 | 20877.0 | 0.01859 | 0 | 40 | 0.190% |
| stream | 2,027 | 28309.0 | 0.01073 | 0 | 40 | 0.110% |
| pointer_chase | 76,863 | 1221881.0 | 0.01479 | 0 | 40 | 0.151% |
| ann | 3,866 | 41229.1 | 0.00417 | 0 | 40 | 0.043% |

Queues show short bursts, not sustained saturation in these phase averages. Queue-full events count rejected admission attempts and do not equal a count of distinct blocked requests. The upstream-port utilization denominator is the modeled 16-byte crossbar width / 417 ps clock (38.37 GB/s per direction), not a verified physical CXL link capacity. Endpoint bandwidth and physical link width/speed are unspecified: endpoint utilization and oversubscription remain unknown. A low average does not rule out brief bottlenecks.

**Native PMU context, not direct counter equivalence.**

| Workload | Native IPC | Native generic cache misses / 1,000 instructions | Native cycles-with-outstanding-data-read fraction | Simulator IPC, whole timing interval |
|---|---:|---:|---:|---:|
| stream | 0.0651 | 105.832 | 98.13% | 0.3119 |
| pointer_chase | 0.0774 | 105.703 | 95.10% | 0.1026 |
| ann | 1.9919 | 0.526 | 81.41% | 0.3044 |

These native fractions indicate frequent outstanding reads, not the fraction of execution stalled on memory and not a direct MLP count. Generic native cache-misses are not automatically equivalent to gem5 L3 demand misses. Native memory_traffic.csv records core mem-loads/mem-stores events, not memory-controller transferred bytes; zero mem-loads must not be interpreted as zero memory traffic. The saved data does not provide a validated matching native per-request memory-latency histogram or DRAM GB/s measurement for these CXL counters.

**What this says about CXL:** the strongest observed cost is request-path latency and its tail (~0.60–0.63 µs P99), with brief admission backpressure. The current successful runs do not demonstrate a CXL bandwidth ceiling, a write bottleneck, or an endpoint-imbalance problem (there is only one endpoint). ANN has an observed application throughput gap, but attributing it to CXL would be unsupported.

For a causal comparison, run identical inputs, binaries, CPU/cache configuration and ROI twice inside SimCXL, changing only local-memory versus CXL placement. Compare simulated ROI time and application throughput; inspect actual placement and traffic, and make the working set exceed the relevant cache when testing memory. Native runs with the same inputs remain useful context but do not isolate the CXL effect. Repair the guest timing/ROI measurements before using short STREAM/ANN kernels for performance conclusions. No new runs were launched for this report.

**Provenance:** simulator source commit 8304d434fdc9c9a4c0a194c3a2a82f0f599686ae; original trial 20260903-065341. Native campaign files are dated 2026-09-01. The companion comparison.json contains numeric observations, selected native repetition values, compact CXL metrics, metadata and SHA-256 hashes of all data files read. compare.py reproduces the report while these source paths remain available. Native and simulator application times, simulator host execution time, and CXL transaction latency are distinct measurements; the ~600× host/sim-time ratio is not a CXL penalty.
