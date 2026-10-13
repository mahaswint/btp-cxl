# Standard trace experiment

**Metric update:** PAC is now the default. This document describes the shared
timing model and original slack experiment. Use `--criticality slack` to reproduce
that experiment; `run_campaign.py` selects it explicitly. For the new PAC
equations, defaults, and campaign, see [PACT_MODEL.md](PACT_MODEL.md).

`trace_profiler.cpp` is a separate event-driven analytical evaluator for public
ChampSim traces. `main.cpp` retains the earlier synthetic phase/lane demos.
Neither executable runs the full ChampSim simulator.

## Reproduce

Run from this directory, using C++17 and Python 3 with its standard library:

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic trace_profiler.cpp -o trace_profiler.exe
g++ -std=c++17 -O2 -Wall -Wextra -pedantic test_trace_profiler.cpp -o test_trace_profiler.exe
./test_trace_profiler.exe
python fetch_traces.py
python run_campaign.py
python summarize_results.py
```

On Linux use executable names without `.exe`. CMake includes both profilers
and a model test. Downloads write 76.8 MB decompressed per trace (230.4 MB total),
plus small JSON provenance manifests. Only the first 1,200,000 instructions are
fetched; downloading and decompressing each complete archive is unnecessary.
Downloaded binaries and executables are ignored by Git. Manifests record the
source and a SHA-256 of the decompressed prefix, not verification of the full
archive's published checksum.

Individual run:

```powershell
./trace_profiler.exe --trace traces/605.mcf_s-1554B.champsimtrace.bin --out results/custom --criticality slack --capacities 16,64,256 --fast-ns 80 --slow-ns 250 --mlp 16
```

Input must be an uncompressed standard 64-byte, little-endian ChampSim trace;
CloudSuite's alternate layout is unsupported. The reader decodes register and
memory operands explicitly, avoiding host structure packing assumptions.

## Sources and segmentation

Public SPEC CPU 2017 traces from [Zenodo record 10960004](https://zenodo.org/records/10960004):

- `605.mcf_s-1554B.champsimtrace.xz`
- `619.lbm_s-2676B.champsimtrace.xz`
- `623.xalancbmk_s-165B.champsimtrace.xz`

Format: [ChampSim input_instr definition](https://github.com/ChampSim/ChampSim/blob/master/inc/trace_instruction.h).
The real instruction order, register operands, and memory addresses come from
these traces. Latencies and resource sizes are assumptions, not observations.

Instruction ranges, counted from the beginning of each published trace file:

- 0–199,999: cache warmup; no placement training.
- 200,000–699,999: training; derive both rankings with all pages slow.
- 700,000–1,199,999: held-out evaluation; keep trained placements fixed.

The functional cache remains warm across these ranges. Register producer and
memory-order histories, ROB state, and timing resource state reset at each
segment boundary; inputs from before a boundary are initially ready. The two
500,000-instruction segments are short pilot samples, not complete applications
or the much longer standard ChampSim benchmark protocol. Page IDs are virtual
addresses divided by 4096, not a simulated operating system's physical mapping.

## Timing model

One unified data cache uses 64-byte lines, 1 MiB capacity, eight ways, and LRU
replacement. Its hits/misses are computed in trace operand order once and held
fixed across placements. Reads and writes both allocate; dirty writeback traffic
is omitted. This approximates the data reaching main memory, rather than a full
L1/L2/LLC hierarchy. Cache-hit operands cost 4 ns each.

Each instruction has an admission event and a completion event. Admission is
in program order, up to four instructions per 0.333333 ns core tick, and limited
by a 192-instruction window with in-order retirement. Completion waits for its
admission, source-register producers, earlier same-line stores, and a reserved
memory slot if it has cache misses. Stores also wait for the preceding same-line
access. Register producers are updated after reading sources, modeling register
renaming for the recorded operands. No instruction opcode is available, so all
instructions use the same 0.333333 ns base compute duration.

Duration = base compute + hit_count * hit_latency + sum(miss page latency).
Multiple memory operands within one instruction are serialized. Different
instructions overlap when dependencies and resources allow it. Each instruction
with misses reserves one of N outstanding-memory slots until it completes.
Reservations are assigned in instruction order to the earliest available slot;
this approximates limited memory parallelism, not an out-of-order issue scheduler
or detailed MSHR coalescing. Retirement chooses the latest completion in the
prefix. Evaluation rebuilds resource edges separately for each placement.

Events jump directly to dependency completion times. There is no cycle stepping,
branch prediction, speculation, prefetching, bandwidth/queue model, instruction
cache, migration cost, or detailed DRAM/CXL protocol simulation.

## Rankings

Frequency ranks pages by **training cache-miss count**, since misses incur the
modeled tier latency. Raw operand-access counts are also exported for inspection.

Criticality uses a forward/backward longest-path pass over the all-slow training
schedule, including register, memory-order, admission, retirement, and memory-slot
edges. Slack is the amount an instruction completion could be delayed without
extending the modeled segment's completion time on that fixed event graph.
Each miss contributes:

```
max(0, slow_latency - fast_latency - instruction_slack)
```

These contributions are summed per page. Thus exposed misses receive more
weight than misses whose latency is hidden by other work. Criticality ties use
miss frequency, then page number; frequency ties use page number. Only pages
that missed during training are candidates. Both policies choose the same
number of equal-size pages; unseen evaluation pages remain slow.

This is an **offline slack-based criticality heuristic**. Its score is neither
measured hardware stall time nor an exact per-page counterfactual speedup. Tied
paths, multiple misses per instruction, interacting page promotions, and changed
resource schedules can invalidate individual score predictions. Held-out replay
measures the resulting modeled outcome instead of treating scores as speedups.

## Campaign and outputs

The campaign sweeps fast capacities 0, 16, 64, 256, 1024 pages; slow latency
160, 250, 400 ns; and outstanding-memory slots 1, 8, 16. Fast latency is 80 ns.
Other parameters use the defaults above. `--help` lists configurable parameters.

- `results/campaign.csv`: all 135 comparisons, including zero-capacity controls.
- Each run's `.csv`: all-slow, frequency, and criticality evaluation runtime,
  placement overlap, selected page count, and reduction relative to frequency.
- `_pages.csv`: training counts, criticality scores, and evaluation miss counts.
- `_placement_N.csv`: selected pages for both policies at each capacity.
- `_config.txt`: exact trace path and model parameters.

Positive reduction means criticality is faster; negative means frequency is
faster. Results show sensitivity under this model, not validated hardware speedup
or proof that criticality always helps. More trace regions, cache configurations,
and validation against a fuller simulator are needed for a stronger conclusion.
