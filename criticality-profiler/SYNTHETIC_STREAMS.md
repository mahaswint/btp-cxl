# Variable-MLP workload demonstration

`synthetic_stream_profiler.cpp` creates deterministic analytical streams and
shares the existing `RuntimePolicy` implementation with the real-trace
profiler. The new execution path aggregates identical batches instead of
scheduling millions of requests separately. No downloads are required.

The workload deliberately separates frequency from exposed memory cost:

* A 4 MiB pointer-chain group issues dependent loads, one at a time.
* A second 4 MiB group has four times as many misses but issues independent
  batches of 1, 2, 4, 8 or 16 loads.
* DRAM has 4 MiB of capacity. Initially both policies contain the same cold
  warmup pages. Active requests start in CXL.
* There are 12 rounds, each containing one phase of each group. The main sweep
  starts with the hot independent group; a separate case reverses that order.

At each batch, requests start together; the next batch depends on the previous
batch's completion. DRAM requests finish after 90 ns and CXL requests after
190 ns. Runtime is the sum of batch completion times and charged copying.
Measured per-tier occupancy area divided by active time supplies MLP.
There is no supplied per-page criticality label or requested speedup.

Every 20 ms, the shared policy estimates stalls as `190 * CXL_misses / MLP`
and attributes them to observed CXL pages. Frequency counts those same misses.
Both use the same 20 bounded bins, reservoir seed and 128-page batch cap.
The total promotion budget is preset to 1,024 pages. Both must actually use
that budget and incur exactly 1,024 demotions and 2.886861 ms of copying.
After budget exhaustion, placement freezes; observations continue. This is
a control for comparing selection under equal total migration counts.

In a pure CXL phase, four times as many accesses with MLP 16 contribute only
one quarter as much estimated stall per page as the serial group:

```
hot relative PAC = 4 / 16 = 0.25
serial relative PAC = 1 / 1 = 1
```

That gives PAC information absent from frequency. At MLP 1 there is no such
information: PAC is a constant multiple of frequency, and the control must
match in both final placement and runtime.

## Build and demonstrate

From this directory:

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic synthetic_stream_profiler.cpp -o synthetic_stream_profiler.exe
./synthetic_stream_profiler.exe
```

The full suite writes [results](results/synthetic_streams/REPORT.md), request
definitions, per-window MLP, migrations and final placement. It processes
25,313,280 analytical load misses per scenario and policy. The six cases take
about a minute on this machine.

For a short demonstration of the MLP-16 case alone:

```powershell
./synthetic_stream_profiler.exe --scenario hot_first_mlp16 --out results/synthetic_streams/demo
```

Use `--rounds N` for 4–100 rounds; report the chosen value because startup
placement and phase lengths affect the result. CMake also builds the executable.

`--alpha A` sets decay for both policies, with `0 <= A <= 1` (default 1).
Every observation applies `score_new = A * score_old + contribution` to tracked
scores. For the requested alpha=0.7 comparison, the same workloads are retained:

```powershell
./synthetic_stream_profiler.exe --scenario hot_first_mlp8 --alpha 0.7 --out results/synthetic_streams/alpha_0_7/mlp8
./synthetic_stream_profiler.exe --scenario hot_first_mlp16 --alpha 0.7 --out results/synthetic_streams/alpha_0_7/mlp16
```

`--window-ms W` sets the observation interval in milliseconds (default 20).
The 10 ms, alpha=0.7 runs use separate output directories:

```powershell
./synthetic_stream_profiler.exe --scenario hot_first_mlp8 --alpha 0.7 --window-ms 10 --out results/synthetic_streams/alpha_0_7_window_10ms/mlp8
./synthetic_stream_profiler.exe --scenario hot_first_mlp16 --alpha 0.7 --window-ms 10 --out results/synthetic_streams/alpha_0_7_window_10ms/mlp16
```

Keeping alpha=0.7 per update halves its decay time scale when changing 20 ms
to 10 ms. The 128-page per-update cap also offers twice as many promotion
opportunities per modeled second. The total budget remains 1,024 promotions.

## What the experiment establishes

These are **synthetic LLC-miss streams**, rather than captured application
instructions. Requests enter after cache filtering, so the engine assumes the
listed requests miss the LLC; it does not simulate or infer cache-hit rates.
It does not model a CPU pipeline, prefetching, coherence, bandwidth contention,
PEBS sample loss or concurrent copying. It also uses the documented policy
approximations from [the PACT audit](PAPER_REPRODUCTION.md).

The measured difference demonstrates that MLP-weighted, accumulated page scores
can choose more useful pages than frequency under these assumptions. It does
not reproduce the paper's hardware percentages, and it should be presented as
a controlled mechanism experiment. All MLP settings, including ties, and the
reversed-order result are retained rather than selecting only a favorable run.

Analytical checks verify serial, parallel, repeated-cycle, partial-batch and
mixed-tier timing. The suite verifies request conservation, equal actual moves
and copy costs, DRAM capacity, and exact equality of the constant-MLP control.
