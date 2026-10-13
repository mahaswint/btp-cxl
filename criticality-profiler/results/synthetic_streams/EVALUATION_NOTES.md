# Evaluation explanation

We test the PACT criticality principle using controlled synthetic memory
streams. One group is accessed frequently but has independent overlapping
loads; another is accessed less frequently but forms a serial pointer chain.
Frequency treats each miss equally. PAC weights misses by the measured
memory-level parallelism of their observation window, which exposes the
greater cost of serial loads.

Both policies use the same DRAM capacity, 20 ms observations, assumed 90/190 ns
DRAM/CXL latencies and page-selection implementation. Both actually perform
1,024 promotions and 1,024 demotions, with the same copy charges. Thus a result
cannot be explained merely by one policy moving fewer pages.

| Independent stream width | Frequency runtime | PAC runtime | Runtime reduction |
|---|---:|---:|---:|
| 1: constant-MLP control | 2,844.84 ms | 2,844.84 ms | 0% |
| 2 | 1,928.62 ms | 1,928.62 ms | 0% |
| 4 | 1,455.96 ms | 1,455.96 ms | 0% |
| 8 | 1,217.41 ms | 1,157.76 ms | 4.90% |
| 16 | 1,093.20 ms | 831.42 ms | **23.95%** |
| 16, reversed phase order | 950.70 ms | 746.98 ms | **21.43%** |

For the main width-16 case, frequency fills DRAM with the frequent independent
pages. PAC keeps 768 serial pages and 256 independent pages in DRAM. Measured
CXL MLP ranges from 1 to 16. The two runs complete 54 and 41 observation windows
respectively because their runtimes differ. Each executes the same 25,313,280
load requests.

The hot group has four times the accesses of the serial group. At overlap 16,
its per-page PAC contribution in a pure phase is proportional to `4/16`, while
the serial group contributes `1/1`. This is why frequency and criticality rank
the groups differently. When overlap is constant at one, PAC becomes a fixed
multiple of frequency and the control matches exactly.

The claim supported here is: **under these controlled workload assumptions,
MLP-aware page scoring reduces modeled runtime relative to access frequency.**
These are synthetic LLC-miss streams with analytical batch execution and a
fixed total migration budget. They demonstrate the scoring mechanism; they
do not reproduce the complete PACT runtime or its hardware results.

For the demonstration, run from `criticality-profiler`:

```powershell
./synthetic_stream_profiler.exe --scenario hot_first_mlp16 --out results/synthetic_streams/demo
```

The [full report](REPORT.md), [raw summaries](summary.csv), [stream definitions](streams.csv)
and [implementation description](../../SYNTHETIC_STREAMS.md) make the result
reproducible. Serial/parallel timing, mixed-tier timing, capacity, load conservation,
equal migration counts and the constant-MLP control passed their checks.
