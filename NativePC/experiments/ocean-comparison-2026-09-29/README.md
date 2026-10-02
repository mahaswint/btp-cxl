# Native baseline for the OCEAN comparison

Copied from `MahaswinBTP/experiments/ocean-cxl-validation-2026-09-29/` without modifying the measurements:

- `chase.c`: dependent pointer chase over a deterministic, shuffled 2 MiB region, with one pointer per 64-byte line and correctness checks.
- `native-before.log`, `native-repeat-before.log`, `native-repeat-after.log`: the original native runs taken around the OCEAN validation and repeat experiment.

For a new smoke test from this folder:

```sh
cc -O2 -o chase chase.c
./chase ram 100000
```

This prints five timed repetitions after initialization and warmup. It does not overwrite the archived logs. This command is a convenient new smoke test, not a claim to reproduce every compiler/affinity setting of the historical experiment. Use identical build settings and workload parameters on both sides of a new simulator/native comparison.

These timings measure the loop, not whole-process runtime. The workload is not a guarantee of an LLC miss on each access. Native logs alone cannot establish a simulator slowdown ratio; the corresponding OCEAN logs, configuration and timing boundaries are also required.
