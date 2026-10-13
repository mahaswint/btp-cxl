# PACT hardware-counter calibration audit

Source pinned to PACT commit `a830e66c30a9beab658943523361e1087d46e809`. Actual CSV has 96 workloads,
although its README describes 95. Hashes and miss/MLP identities were verified.

Fit: measured LLC stall cycles = k × (LLC misses / measured MLP), through the origin.
Leave-one-out error evaluates each workload with its own row excluded from fitting.

| Tier | Approximate tier label ns | Fitted k cycles | Miss correlation | Miss/MLP correlation | LOO mean absolute error |
| --- | ---: | ---: | ---: | ---: | ---: |
| local_dram | 90 | 238.003 | 0.8961 | 0.9740 | 36.06% |
| remote_numa | 140 | 441.591 | 0.8456 | 0.9767 | 31.82% |
| cxl_emulated | 190 | 771.070 | 0.8288 | 0.9739 | 39.69% |

The fitted local/slow values reproduce the artifact's rounded 238/771 constants.
These coefficients describe effective stalls. They are not memory-service latency in nanoseconds.
The CSV's offcore_load_latency fields are retained as source data but not used as nanoseconds:
their measurement provenance/clock conversion is not established by the checked-in collector,
which writes zero placeholders for these fields in newly collected rows.

## Real-CXL artifact checked

Melody's EMR CXL-A CSV contains 264 whole-workload runtime ratios versus local memory.
MIO documentation describes averaged pointer-chase latency samples, but the inspected repository
does not include the corresponding raw measurement logs. Slowdown ratios cannot identify
per-access latency, queue delay, or page-address timing. Neither artifact supplies a timed
instruction/request trace interchangeable with our ChampSim inputs.

## Applying this evidence

Use run_pact_reference.py for an explicitly approximate 90/190 ns service-latency scenario.
It retains the original baseline defaults elsewhere. Optionally declare --score-clock-ghz
to convert the fitted cycle coefficients for score scaling; that clock is an explicit
conversion assumption, not recovered measurement metadata. Runtime core timing is unchanged.
Because only CXL misses add PAC scores, changing a fixed positive CXL k alone generally
rescales the scores without adding page-level information or changing rankings.

Exact observed request latency would require matching issue/completion timestamps or
documented per-load latency samples with units and tier attribution. Moving pages changes
queuing and overlap, so even a fixed replay of observed latencies is not exact for new placements.

Sources: [PACT modeling](https://github.com/MoatLab/PACT/tree/main/modeling),
[PACT PMU coefficients](https://github.com/MoatLab/PACT/blob/main/src/pmu-platform.c),
[Melody](https://github.com/MoatLab/Melody).

## Reproduce

```powershell
python calibrate_pact_reference.py
python run_pact_reference.py --trace traces/graph/bc_bc.twitter-876B.champsimtrace.bin --out results/pact_reference/bc_twitter876_1m_200us --instructions 1000000 --window-ns 200000 --score-clock-ghz 3
```

The explicit 3 GHz conversion matches the profiler's default core-tick assumption;
it is not evidence that the measurement server ran at 3 GHz. This 1M replay is a
functional check of the profile path, not a measured hardware performance result.
Omit --score-clock-ghz to use nominal latency as k, preserving the previous scoring convention.
Both variants are estimates. The calibration-only coefficients remain in cycles in reference_profile.json.
