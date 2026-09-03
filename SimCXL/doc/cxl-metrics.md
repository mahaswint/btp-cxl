# Simulator-internal CXL metrics

The collector instruments timing-mode CXL.mem traffic through `CXLBridge`,
`CXLMemCtrl`, `CXLType2Accel`, and the noncoherent crossbar ports on those paths.
Collection is opt-in. It writes request lifecycle events to `cxl-events.jsonl`;
the standard-library-only reporter produces `cxl-metrics.json` with run metadata,
flat metric names, raw fixed-window byte counts, exact histograms, and phase reports.
It does not change queue sizes, timing, arbitration, placement, or bandwidth limits.

## Run

Build with `scons build/X86/gem5.opt -j2`, then run:

```sh
python3 util/cxl_metrics.py run \
  --output-dir m5out/cxl-example \
  --workload mixed-traffic --placement-policy fixed --cxl-version 3.0 \
  --random-seed 5489 --window-ticks 100000 \
  -- build/X86/gem5.opt tests/cxl/metrics_smoke.py
```

The smoke configuration needs no kernel or disk image. It uses two CXL Type 3
endpoints, a shared crossbar, small queues, and mixed traffic. Substitute your
configuration and its arguments after the binary. The runner seeds gem5's RNG,
records the current source commit and dirty state, and writes the report after
a successful simulator exit. Use a fresh output directory for each run. The
runner expects the binary immediately followed by the configuration script;
it supplies gem5's output-directory option itself.

For existing launch workflows, set `SIMCXL_METRICS_TRACE` before starting gem5,
then postprocess the trace with:

```sh
python3 util/cxl_metrics.py report \
  --trace m5out/cxl-events.jsonl --config m5out/config.json \
  --metadata m5out/cxl-run.json --output m5out/cxl-metrics.json \
  --window-ticks 1000000
```

The metadata JSON must contain `run_id`, `workload`, `placement_policy`,
`cxl_version`, `random_seed`, and `commit_sha`. A manually launched run must
supply its actual seed and build/source identity. The runner records the checked-out
commit; `source_dirty` identifies changes beyond that commit. Build the current
sources before using the runner.

Set reporting capacities on each bridge/endpoint in the configuration:

```python
endpoint.metrics_read_bandwidth = 32e9   # decimal payload bytes/second
endpoint.metrics_write_bandwidth = 16e9
endpoint.metrics_link_width = 16         # lanes
endpoint.metrics_link_speed = 32         # GT/s per lane, metadata only
```

These are denominators, not new throttles. An unspecified capacity is represented
by `null`, not zero utilization. Crossbar payload capacity is derived from its
actual configured width in bytes and clock period. Lane count and GT/s are
separate metadata and are never silently substituted for payload GB/s.

## Metric catalogue

`cxl` reports global traffic once, at endpoint boundaries. `cxl.endpoint.N` uses
stable, lexicographically sorted endpoint paths; `cxl.link.N` identifies observed
bridge or crossbar ports. Metadata maps numeric IDs back to paths. Endpoints
with no requests remain in the report and imbalance calculations. Crossbar ports
are discovered when first traversed by CXL traffic; unused crossbar ports are
not presented as measured links.

| Family | Exported metrics |
|---|---|
| Transactions | `read_requests`, `write_requests`, `atomic_requests`, `total_requests` |
| Payload | `read_bytes`, `write_bytes`, `total_bytes` |
| Latency | `read_latency_ticks`, `write_latency_ticks`: count, min, mean, p50, p95, p99, max, exact histogram |
| Breakdown | `latency.fabric`, `latency.queue`, `latency.device`, `latency.return_path`, `latency.total`, each a distribution |
| Windows | `cxl.window.read_bytes`, `cxl.window.write_bytes`, begin/end ticks, demand bytes, and directional/combined GB/s |
| Bandwidth | `read_bandwidth_GBps`, `write_bandwidth_GBps`, `combined_bandwidth_GBps`, and corresponding `peak_*` metrics |
| Utilization | `read_utilization`, `write_utilization`, `combined_utilization` |
| Behavior | `read_ratio`, `write_ratio`, `read_only_time`, `write_only_time`, `bidirectional_time`, `idle_time`, `bidirectional_overlap` |
| Queues | `read_queue_depth`, `write_queue_depth`, `total_queue_depth`: time-weighted mean, p50, p95, p99, max and histogram |
| Congestion | `queue_full_events`, `backpressure_cycles`, `backpressure_ticks`, `bandwidth_stall_cycles`, `oversubscribed_windows`, `oversubscribed_time_fraction`, `excess_demand_bytes` |
| Imbalance (global) | `endpoint_bandwidth_cv`, `endpoint_busiest_to_average`, `endpoint_request_imbalance` |

Endpoint and link aliases include `read_latency`, `write_latency`,
`read_bandwidth`, `write_bandwidth`, `queue_depth`, and `utilization`. Latency
aliases retain ticks; bandwidth aliases retain GB/s. Request and response queues
are separately available as `request_queue.*_queue_depth` and
`response_queue.*_queue_depth`. Tier aggregates are
`cxl.host.*_queue_depth`, `cxl.switch_port.*_queue_depth`, and
`cxl.device.*_queue_depth`. The unqualified queue alias refers to request queues.

## Definitions and model boundaries

- **Issue:** the first timing request attempt at the outer CXL bridge, or the
  first CXL crossbar/endpoint when there is no bridge. Time spent in CPU caches
  or other upstream components is outside this boundary. Rejection/retry does
  not increment the transaction count again. Endpoint attribution uses the
  configured address ranges, including requests still waiting at the host.
- **Transactions:** reads, writes, and atomic operations are mutually exclusive
  classes. An atomic operation transfers payload in both directions. Gem5's
  `recvAtomic` execution mode is not a CXL atomic operation; atomic-mode boot,
  functional accesses, and CXL.io/accelerator CXL.cache traffic are excluded.
- **Bytes:** payload bytes, counted at successful request sends for writes and
  successful response sends for reads. Packets are credited to the window
  containing the send event. Protocol headers and framing are excluded. A
  request crossing several links contributes once globally and once per link.
- **Latency:** first host issue to successful response delivery at the same
  boundary, including admission and response backpressure. Histograms use exact
  integer tick buckets and nearest-rank percentiles. Posted requests without a
  response do not receive fabricated latency samples. `incomplete_requests`
  exposes outstanding work at the report boundary.
- **Six timestamps:** host issue; first fabric enqueue; endpoint FIFO enqueue;
  backend request acceptance; backend response arrival; host completion. With
  these named `H,F,E,S,D,C`, the components are `fabric=E-F`,
  `queue=(F-H)+(S-E)`, `device=D-S`, `return_path=C-D`, `total=C-H`.
  They sum exactly for every complete sample. Fabric time includes intermediate
  switch residence, whose queue distributions are separately reported.
- **Device service boundary:** the current implementation measures residence in
  the backend memory subsystem, including its internal scheduling. It does not
  identify an individual DRAM row/burst service start. Buffered write responses
  mean acknowledgement, not persistence. Separating backend DRAM scheduling
  from the medium would require additional memory-controller instrumentation;
  the report explicitly records this limitation instead of labeling it pure
  media latency.
- **Time windows:** fixed tick-zero-aligned windows, clipped at phase and run
  boundaries. Idle windows are retained. The denominator of a partial window
  is its actual duration. A peak combined rate is the maximum of window sums,
  not the sum of independent read/write peaks. `GB/s = bytes * tick_frequency /
  elapsed_ticks / 1e9`. Window size is required to be positive; use sufficiently
  coarse windows for long full-system runs to avoid excessive output.
- **Utilization:** directional throughput divided by configured directional
  capacity; combined throughput divided by their sum (full-duplex convention).
  Global denominators sum endpoint capacities and require every endpoint's
  capacity. Values can exceed one because reporting parameters do not impose
  a new model throttle.
- **Ratios:** read/(read+write) and write/(read+write) transaction counts,
  excluding atomics; both zero for an empty read/write population.
- **Directional activity:** unions of actual payload-bearing crossbar occupancy
  intervals. Endpoint/bridge activity uses the transport traversed by that
  endpoint's requests. `overlap=both/either`, zero when either-active time is
  zero. Durations are ticks; adjacent intervals do not overlap. A direct path
  without a modeled crossbar serialization interval reports activity as `null`.
  These intervals are the simulator's crossbar occupancy, not a physical CXL
  PHY/flit model.
- **Queue distributions:** integrate occupancy over time, including initial,
  trailing, and phase-clipped idle intervals. Histogram weights are ticks.
  Atomics occupy the read-class queue once. Crossbar queue depth measures CXL
  retry waiters whose packets remain at the source; it is not a fictional
  finite packet FIFO. Its FIFO capacity is therefore `null`.
- **Backpressure:** union of admission, outbound-request, and outbound-response
  blocked intervals. Overlapping causes are not added twice. Cycles use the
  node's clock period. A global duration in ticks is always available; a global
  cycle count is `null` when clock periods differ.
- **Bandwidth stalls:** intersection of actual crossbar serialization occupancy
  and CXL requests waiting for arbitration. Shared response layers are tracked
  as shared resources. Downstream-device waiting alone is not bandwidth stall
  time. FIFO-only bridge/endpoint nodes lack a bandwidth-specific cause and
  report `null`; global and crossbar-port values come from the modeled fabric.
- **Oversubscription:** offered endpoint bytes at host issue (port-arrival bytes
  for links) beyond directional window capacity. Excess demand sums positive
  directional excesses. A window is oversubscribed if either direction is over
  capacity. The time fraction weights actual window durations. This is a demand
  diagnostic; observed queue/backpressure metrics establish actual congestion.
- **Imbalance:** population standard deviation of endpoint bandwidth divided by
  its mean; maximum endpoint bandwidth divided by mean; maximum endpoint request
  count divided by mean request count. Empty populations return zero.

## Named phases

Guest C/C++ code supplies names only. Link with the usual guest `libm5`:

```cpp
#include <gem5/simcxl_phase.h>

simcxl_phase_begin("prefill");
// workload
simcxl_phase_end("prefill");
```

Markers use reserved work-item arguments; ordinary workbegin/workend behavior
is unchanged. Names must be fewer than 256 bytes. Begin/end calls must be paired;
a name cannot overlap itself, while distinct named phases may overlap. Repeated
nonoverlapping names produce separate snapshots. An open phase at exit is
reported with `complete: false`. Invalid marker sequences cause reporting to
fail rather than producing misleading snapshots.

Each phase is an interval report with request and byte deltas, latency samples
for requests completing in that interval, bandwidth, utilization, integrated
queue state, backpressure, and all endpoint/link traffic. Work already in flight
at phase begin retains its original issue timestamp. Percentiles are recomputed
from phase samples, never subtracted. Intervals are half-open; the whole-run
report additionally includes events exactly at the final simulation tick.
Ordinary gem5 stats resets do not reset this CXL lifecycle collector. Use phases
to isolate the timing-mode ROI after boot. Trace/report files preserve run
metadata, topology connections, endpoint capacities, timing parameters, queue
capacities, clock frequency, seed, source identity, and explicit unavailable
values.

## Scope relative to native measurements

No native-PC or workload measurements are reimplemented here. The finalized
ownership split is:

| Existing/native or application collector | SimCXL collector |
|---|---|
| Runtime, application throughput/QPS, application latency and median/p95/p99 | CXL request end-to-end latency distributions |
| Instructions, cycles, IPC/CPI, CPU utilization, memory-stall time | CXL FIFO/backpressure and fabric bandwidth-stall time |
| LLC accesses/misses/MPKI, DTLB accesses/misses | CXL endpoint and link transactions/payload |
| Host memory bytes/bandwidth/ratio/intensity, footprint/working set | CXL-only bytes/bandwidth/ratios/utilization |
| MLP and locality/random-versus-sequential behavior | CXL queue distributions and directional overlap |
| LLM prefill/decode duration and throughput, TTFT, tokens/s, time/output token | Named prefill/decode CXL interval reports |

Use matching run IDs and phase names when joining external baseline data. No
native capture, application counters, CPU/cache/TLB counters, migration, hotness,
cache-hit policy, semantic object tracking, energy, fairness, or detailed
coherence metrics are added.

## Validation

```sh
python3 -m unittest discover -s tests/cxl -p 'test_*.py' -v
```

The analytical tests exercise quantiles, idle-weighted queues, retry deduplication,
atomic classification, phase crossing, partial windows, capacity excess, byte
attribution, overlap, latency additivity, and bandwidth versus downstream waiting.
A rebuilt simulator and the smoke run above are additionally required to validate
the C++ integration after changes to collector hooks.
