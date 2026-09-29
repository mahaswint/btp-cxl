# OCEAN direct-path runtime baseline

Date: 2026-09-29

## Purpose

Measure the current OCEAN direct memory-server request path against an equivalent native in-memory loop before implementing PIPM.

## Environment

- CPU: Intel Core i7-12700 (20 logical CPUs)
- RAM: 15 GiB
- Kernel: Linux 7.0.0-31-generic x86_64
- OCEAN import: `c712cfa4194a041a3f390626a2abc150a29e4cbc`
- Build: Release, GCC 14.2.0
- Repetitions: 5 per configuration

## Method

Each iteration fills a buffer, writes it to an 8 MiB region, reads it back, and verifies the result. The native case uses local `memcpy`. The OCEAN case uses the repository's `legomem_qemu_bench` and `legomem_server` over loopback TCP. Reported values are medians of five repetitions.

| Transfer size | Iterations | Native median | OCEAN median | OCEAN/native | Native MiB/s | OCEAN MiB/s |
|---:|---:|---:|---:|---:|---:|---:|
| 64 B | 100,000 | 0.005174 s | 1.545977 s | 298.82x | 2359.5 | 7.9 |
| 4 KiB | 20,000 | 0.026197 s | 0.516013 s | 19.70x | 5964.4 | 302.8 |
| 64 KiB | 1,000 | 0.023942 s | 0.182726 s | 7.63x | 5221.0 | 684.1 |

## Interpretation

The direct path is highly sensitive to request size. Cache-line requests pay one synchronous TCP round trip per read or write and are roughly 299x slower than the equivalent local-memory loop. Batching at page and 64 KiB granularity reduces the observed multiplier substantially.

This is a data-path microbenchmark, not a whole-application slowdown measurement. A real workload that performs computation between remote accesses can have a lower total multiplier. However, the 64 B result is directly relevant to a PIPM implementation that observes or redirects every cache line.

The current QEMU `memory-backend-legomem` is not suitable for a full-application comparison yet: it allocates a normal RAM `MemoryRegion` and records server metadata, but it does not forward guest memory operations to the OCEAN server. Timing a KVM guest through that backend would therefore produce a misleading near-native result.

## Reproduction

Build the direct integration:

```bash
cmake -S qemu_integration -B qemu_integration/build -DCMAKE_BUILD_TYPE=Release
cmake --build qemu_integration/build -j
ctest --test-dir qemu_integration/build --output-on-failure
```

Raw measurements are in `raw-results.tsv` with columns:

```text
block_size_bytes  repetition  iterations  native_seconds  ocean_seconds
```
