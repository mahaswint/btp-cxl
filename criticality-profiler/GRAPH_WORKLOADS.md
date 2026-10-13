# Testing PAC on graph workloads

The original SPEC pilot often has too little policy activity or MLP variation
to separate PAC from frequency. For a single slow-tier sampling window, every
page receives the same unit weight `k/MLP`, so PAC ranking is proportional to
frequency. Meaningful differences require phase-dependent weights accumulated
over multiple observations, different subsequent reuse, or different migration
behavior. A workload name alone does not establish that those conditions exist.

The PACT paper evaluates graph workloads including betweenness centrality on
Kronecker/Twitter graphs and triangle counting on Twitter. These mix dependent
accesses and other traversal patterns. We therefore added real public GAP
instruction traces from the same workload families, rather than constructing
traces to produce a desired speedup.

Sources:

- [PACT paper](https://huaicheng.github.io/p/asplos26-pact.pdf), sections 3 and 5.
- [GAP and XSBench ChampSim trace release](https://zenodo.org/records/20043527).
  The dataset authors request citation of "Characterizing the impact of
  last-level cache replacement policies on big-data workloads" (IISWC 2020).
- [GAP Benchmark Suite](https://arxiv.org/abs/1508.03619).

Selected trace regions, fixed before measuring outcomes:

| Workload | Archive | Member |
| --- | --- | --- |
| Betweenness centrality, Kronecker graph | bc_traces.zip | bc.kron-2608B.champsimtrace.xz |
| Betweenness centrality, Twitter graph | bc_traces.zip | bc.twitter-309B.champsimtrace.xz |
| Triangle counting, Twitter graph | tc_traces.zip | tc.twitter-34B.champsimtrace.xz |

For each workload family we selected the earliest instruction-region label
listed in the archive. These are not necessarily the graph sizes, thread counts,
or trace regions used in PACT's own experiments. The evaluator models one
instruction stream, not PACT's full multithreaded application execution.

Each trace prefix contains 12.2 million instructions: 200k cache warmup followed
by 12 million continuously executed instructions. The downloader uses byte-range
requests to access individual ZIP members and stops decompression at the desired
prefix. It does not download the complete multi-GB archives. Each prefix occupies
780.8 MB, totaling 2.3424 GB for these three additional traces. JSON manifests
record archive/member URLs, sizes, fetched-byte counts, and prefix SHA-256 hashes.
The full archive/member checksums are not verified when taking only a prefix.

### Highest-weight regions

The release's published region weights showed that the first triangle-counting
region accounts for only 6.72% of execution. A follow-up selects the highest-weight
available region in each family, using weights rather than measured speedups:

| Workload | Member | Published weight |
| --- | --- | ---: |
| bc-kron | bc.kron-5154B.champsimtrace.xz | 47.56% |
| bc-twitter | bc.twitter-876B.champsimtrace.xz | 47.46% |
| tc-twitter | tc.twitter-4460B.champsimtrace.xz | 38.08% |

`inspect_graph_weights.py` records the published weights in
`traces/graph/published_weights.json`. Each additional prefix also contains
12.2 million records; six prefixes together occupy 4.6848 GB.
Individual regions still do not capture a full application's changing phases.

## Reproduce

```powershell
python fetch_graph_traces.py --archive bc_traces.zip --member bc.kron-2608B.champsimtrace.xz --records 12200000
python fetch_graph_traces.py --archive bc_traces.zip --member bc.twitter-309B.champsimtrace.xz --records 12200000
python fetch_graph_traces.py --archive tc_traces.zip --member tc.twitter-34B.champsimtrace.xz --records 12200000
python run_graph_campaign.py
python summarize_graph_results.py
```

For the highest-weight follow-up, fetch the three members in the second table
with the same record count, then run:

```powershell
python run_graph_campaign.py --representative
python summarize_graph_results.py --representative
```

The follow-up report is [here](results/graph_representative/REPORT.md).

Build `dynamic_profiler` first, as described in [DYNAMIC_MODEL.md](DYNAMIC_MODEL.md).

The prespecified sweep uses 20 ms windows at 64/256/1024 DRAM pages, plus an
explicitly labeled 1 ms sensitivity run at 256 pages. No extra eager reserve is
used. Latencies are 80 ns DRAM and 250 ns CXL, with 16 outstanding-memory slots,
64-page promotion batches, 10 GB/s migration bandwidth, and 1000 ns overhead
per moved page. These settings do not change based on measured outcomes.

Both policies share first-touch placement, sample only observed CXL load misses,
use adaptive bins and cold-page demotion, and pay identical migration costs.
All-CXL and all-DRAM runs provide references. Runtime results, migration counts,
observed MLP range, and policy decision counts are exported for every case.

[Results](results/graph/REPORT.md) include all wins, ties, and losses. Improvements
are modeled results under a simplified cache/CPU and synchronous migration model,
not measurements of the actual PACT runtime. A lack of benefit can reflect either
the trace region or the model; this experiment cannot identify which without
additional validation against longer applications or a fuller simulator.

## Observed outcomes

All 24 comparisons across six real regions are retained. At 20 ms sampling,
the policies tie in every case: most runs finish before the first update;
bc-twitter region 876 allows only one update, whose PAC ordering equals frequency.
At 1 ms sampling with 256 DRAM pages:

| Workload | Initial region: runtime reduction vs frequency | Highest-weight region: reduction |
| --- | ---: | ---: |
| bc-kron | +0.243% | +0.038% |
| bc-twitter | +1.459% | -0.082% |
| tc-twitter | 0.000% | -0.120% |

The positive reductions largely track lower migration-copy time. In particular,
the initial bc-twitter PAC run saves about 0.291 ms against frequency while
saving about 0.290 ms in copy costs; both runs are slower than all-CXL.
This demonstrates differing policy behavior, not a large benefit from placing
critical pages. The next informative evaluation requires longer continuous
execution with changing overlap and recurring pages, or full applications with
the paper's multithreaded and overlapping-migration behavior. Selecting another
workload name alone does not resolve the current observation/model limitations.

## Continuous length/window follow-up

`run_window_campaign.py` compares the same bc-twitter region 876 at 12M and
48M runtime instructions, with 200k warmup and 20/5/1/0.2 ms update periods.
DRAM capacity is fixed at 256 pages; all other model settings stay the same.
This uses a longer continuous prefix, without trace looping or concatenation.
The two matching 12M cases reuse the previous measurements; all new cases have
the same accounting checks. This is a fixed sweep, not tuning to select a win.

```powershell
python fetch_graph_traces.py --archive bc_traces.zip --member bc.twitter-876B.champsimtrace.xz --records 48200000
python run_window_campaign.py
```

The enlarged prefix contains 48.2M records (3.0848 GB), all used by the longer
cases including warmup. It replaces this member's original short-prefix file and
manifest; other downloaded members are unaffected. The earlier file-size totals
describe the initial download. [Results](results/graph_windows/REPORT.md) retain
every case, with runtime, update count, migration cost, and all-CXL/DRAM references.

The completed length/window sweep gives these reductions versus frequency:

| Update window | 12M instructions | 48M instructions |
| --- | ---: | ---: |
| 20 ms | 0.000% | 0.000% |
| 5 ms | 0.000% | -0.002% |
| 1 ms | -0.082% | +0.249% |
| 0.2 ms | +7.161% | +10.065% |

The 48M/20 ms case performs four updates and still ties; lack of updates is
therefore not the only explanation. At 0.2 ms, frequency takes 96.424 ms and PAC
86.719 ms. Promotions fall from 4308 to 911. Copy-cost savings account for about
98.7% of the 9.705 ms total reduction. PAC remains 2.70% slower than the 84.438 ms
all-CXL reference in that case. This is evidence of better migration control,
with a much smaller residual execution benefit. Sampling computation overhead
is currently zero, so these shorter periods require further validation before
making claims about a real runtime system. All eight comparisons passed checks.
