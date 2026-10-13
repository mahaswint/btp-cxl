# MahaswinBTP

This repository brings together native-PC experiments and the two simulator codebases used for the CXL BTP:

- `SimCXL/`: the current SimCXL research working tree, including local modifications.
- `OCEAN/`: the OCEAN CXL emulation framework being evaluated for the planned PIPM prototype. Imported from `fam-emu/OCEAN` at commit `c712cfa4194a041a3f390626a2abc150a29e4cbc`.
- `NativePC/`: native workload sources, profiling scripts, recorded runs, processed results, plots and machine information. See [NativePC/README.md](NativePC/README.md) for provenance and setup limitations.
- `criticality-profiler/`: standalone C++ analytical comparison of criticality-based and frequency-based memory placement using assumed latencies. See [criticality-profiler/README.md](criticality-profiler/README.md) for the model, examples, and CSV input.

Large generated builds, VM images, model weights and local Python environments are excluded from version control. The recorded native measurements in `NativePC/` are intentionally included; simulator build/runtime exclusions remain in place.
