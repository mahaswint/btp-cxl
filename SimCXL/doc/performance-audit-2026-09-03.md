# Cache and simulator-overhead audit — 3 September 2026

Evidence comes from the archived [smoke suite](../results/2026-09-03_smoke-trial_065341/README.md),
its saved `config.json`/`stats.txt`/CXL reports, local original trace sizes,
the imported native study's `system_info/system_baseline.txt`, and current source.
No new simulation or build was run during this audit.

## Cache configuration

`guest/simulate.py` copied the upstream
`configs/example/gem5_library/x86-cxl-type3-with-classic.py` configuration:
48 KiB L1D, 32 KiB L1I, 2 MiB L2, and a 96 MiB, 48-way L3. Saved configuration
confirms L3 size 100663296 bytes; this was not inferred from a comment.
The partner's recorded i7-12700 has a 25 MiB L3. The simulation is not a
calibrated replica of that CPU. L3 tag and data latencies also default to
96 cycles each; capacity alone does not specify comparable cache behavior.

Cache capacity can now be selected with `guest/run.py --l2-size ... --l3-size ...
--l3-assoc ...`. The old defaults remain for reproducing existing runs. For
example, `--l2-size 512KiB --l3-size 8MiB --l3-assoc 16` specifies a smaller
experimental hierarchy, not a validated model of the native PC. Choose size and
associativity compatible with gem5's cache indexing; do not substitute an
arbitrary hardware capacity while retaining 48 ways.

## The roughly 600x ratio

The saved STREAM run committed 117316130 instructions over 0.156870 simulated
seconds and 106.18 host seconds: about 748 million instructions per simulated
second versus 1.105 million per host second, yielding 677x. The simulator's
configured clock is 417 ticks/cycle at 1e12 ticks/second, approximately 2.4 GHz.
`RootStats::resetStats` resets both the host timer and simulated start tick.
There is no evidence of a seconds/ticks mismatch or accidental inclusion of
KVM boot in just one denominator. This checks accounting, not whether execution
speed is optimal. Host contention and tracing's individual costs remain unmeasured.

## Tracing overhead is unmeasured but substantial output is confirmed

| Run | Raw trace MiB | CXL payload bytes, whole run | Trace bytes / payload byte |
|---|---:|---:|---:|
| Memory pilot | 93.50 | 1312192 | 74.72 |
| STREAM | 140.90 | 1970752 | 74.97 |
| ANN | 440.46 | 6027328 | 76.63 |

These ratios describe output volume, not runtime overhead. The recorder creates
JSON fields, quotes node/event strings through string streams, looks up requests,
and writes many events per transaction. File writes are buffered; the source
does not flush the file for every event. A matched trace-off/on run is needed
before assigning a percentage of runtime to this work.

## Measurement region and initialization

| Run | Timing interval, simulated seconds | Named workload phase, simulated seconds | Outside phase |
|---|---:|---:|---:|
| Memory pilot | 0.125823 | 0.017326 | 86.2% |
| STREAM | 0.156870 | 0.045628 | 70.9% |
| ANN | 0.475183 | 0.366232 | 22.9% |

These are simulated-time fractions; host-time fractions cannot be recovered
from those phase timestamps. Switching to timing mode currently happens before
launching the workload shell. The interval includes wrapper startup, reporting
and guest output export. Even the named workload phase surrounds the entire
process: Python imports, model/data initialization, warmup, and inference all
run in timing mode. The three interrupted Python jobs reached billions of
guest instructions; available logs do not establish which initialization or
compute stage consumed that work. ROI markers inside the programs, and careful
fast-forward/warmup/checkpoint design, would distinguish those costs.

## CPU model limits

The saved run uses `BaseTimingSimpleCPU`, not O3. According to the
[gem5 SimpleCPU documentation](https://www.gem5.org/documentation/general_docs/cpu_models/SimpleCPU),
TimingSimpleCPU stalls on cache accesses while waiting for responses. A single
such core does not reproduce modern out-of-order memory-level parallelism and
is a weak basis for a saturation study. O3 is available through `--cpu o3`, but
is a different CPU model and may increase simulation cost. Bigger allocations
alone do not ensure useful bandwidth saturation.

## Next measurement (user-run)

```bash
python3 guest/benchmark_overhead.py \
  --output-dir /tmp/simcxl-trace-ab-$(date +%Y%m%d-%H%M%S)
```

This runs STREAM smoke twice at the same cache/core/input/seed settings with
KVM boot, once without CXL tracing and once with it. It requires existing guest
assets and a built binary; it does not build or alter the installed disk image.
No trial timeout is added. `comparison.json` records paired final statistics,
simulation/report wall times, raw host-time ratio, time-per-instruction ratio,
and guest instruction/simulated-time differences. Check those differences;
KVM initialization and host load can vary. One pair is an initial diagnostic,
not proof of a precise tracing cost. `--order on-off` permits a subsequent
reverse-order comparison if the first result needs confirmation. `--dry-run`
prints commands without starting simulations.

The trace-off run deliberately produces no CXL report and must not be treated
as a CXL dataset. The normal suite runner continues to require CXL reports.
Configuration wrappers and the diagnostic are Python changes, so no simulator
rebuild is required just to run this comparison.

The next workload-size decision should be based on this measurement and an
explicit target cache/CPU configuration. Avoid treating the current smoke set
or the native campaign's full sizes as already validated simulator benchmarks.
