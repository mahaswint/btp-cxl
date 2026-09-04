"""Read existing successful results only; never launches a workload."""
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NATIVE = Path('/home/mahaswin/Downloads/BTP_CXL_Study')
SIM = ROOT / 'results/2026-09-03_smoke-trial_065341'
POINTER = Path('/tmp/simcxl-recovered-20260903-170141/pointer_chase-cxl-metrics.json')
SOURCES = {}


def read(p):
    data = p.read_bytes()
    SOURCES[str(p)] = hashlib.sha256(data).hexdigest()
    return data.decode()


def summarize(values):
    return dict(n=len(values), mean=statistics.mean(values),
                sample_std=statistics.stdev(values) if len(values) > 1 else None,
                min=min(values), max=max(values), values=values)


def compact(v):
    return {k: compact(x) for k, x in v.items() if k not in ('histogram', 'windows')} if isinstance(v, dict) else v


native = {}
for w in ['stream', 'pointer_chase', 'ann']:
    rows = list(csv.DictReader(read(NATIVE / f'raw_data/{w}/native_campaign/campaign_status.csv').splitlines()))
    values = {}
    for row in rows:
        assert row['status'] == 'SUCCESS'
        folder = NATIVE / f'raw_data/{w}/native' / Path(row['raw_dir']).name
        status = read(folder / 'status.csv')
        text = read(folder / 'stdout_core_cache.log')
        read(folder / 'command.txt')
        if w == 'stream':
            found = {name + '_GBps': float(value) / 1000 for name, value in re.findall(r'^(Copy|Scale|Add|Triad):\s+([\d.]+)', text, re.M)}
        elif w == 'ann':
            found = {name: float(value) for name, value in re.findall(r'^(BUILD_TIME_SEC|SEARCH_TIME_SEC|QPS)=([\d.]+)', text, re.M)}
        else:
            found = {'ns_per_dereference': float(text.strip())}
        for k, v in found.items():
            values.setdefault(k, []).append(v)
    native[w] = {k: summarize(v) for k, v in values.items()}

sim = {}
for w in ['memory_pilot', 'stream', 'pointer_chase', 'ann']:
    status = json.loads(read(SIM / w / 'guest-run-status.json'))
    assert status['completed']
    if w == 'pointer_chase':
        report = json.loads(read(POINTER))
        phase = next(p for p in report['phases'] if p['metadata']['phase'] == 'workload')
    else:
        phase = json.loads(read(SIM / w / 'cxl-workload-summary.json'))
    assert phase['metadata']['complete']
    metrics = compact(phase['metrics'])
    meta = phase['metadata']
    hz = meta['simulation_tick_frequency']
    ns = {name: {key: value * 1e9 / hz for key, value in metrics['cxl.' + name].items() if key != 'count' and value is not None}
          for name in ['read_latency_ticks', 'latency.fabric', 'latency.queue', 'latency.device', 'latency.return_path']}
    text = read(SIM / w / 'stats.txt')
    blocks = re.findall(r'Begin Simulation Statistics[^\n]*\n(.*?)---------- End Simulation Statistics', text, re.S)
    stats = {}
    for line in blocks[-1].splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in ['simSeconds', 'hostSeconds', 'simInsts', 'board.processor.switch.core.ipc']:
            stats[fields[0]] = float(fields[1])
    sim[w] = dict(input=json.loads(read(SIM / w / 'workload-config.json')),
                  workload_stdout=read(SIM / w / 'workload.log'), stats=stats,
                  phase_seconds=(meta['end_tick'] - meta['begin_tick']) / hz,
                  phase_metadata=meta, cxl_metrics=metrics, latency_ns=ns)

# Keep source-native PMU labels; these are not gem5-equivalent counters.
pmu = [r for r in csv.DictReader(read(NATIVE / 'processed_data/workload_summary.csv').splitlines())
       if r['workload'] in native]
pilot = []
for p in sorted((NATIVE / 'raw_data/memory_pilot/native').iterdir()):
    pilot.append(dict(directory=str(p), command=read(p / 'command.txt').strip(),
                      stdout=read(p / 'stdout_core_cache.log').strip()))
read(NATIVE / 'system_info/system_baseline.txt')
result = dict(native_selection='stdout_core_cache.log from each of five successful campaign repetitions; not all six perf-group executions',
              native=native, native_pmu=pmu, native_pilot=pilot, simulator=sim,
              causal_cxl_slowdown=None, source_sha256=SOURCES)
(OUT / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')

lines = ['# Native BTP study versus successful SimCXL runs — 4 September 2026', '',
'**Finding: these results expose modeled CXL latency, but cannot establish a native-versus-CXL performance penalty.** Input sizes, CPU model, caches, concurrency, software environment and timing boundaries differ. No matched local-memory simulator baseline is present in the inspected result set.', '',
'Four workloads completed: memory_pilot, STREAM, pointer_chase and ANN. Pointer chase is included using its recovered report; its original suite status was a reporting failure, not a failed guest workload. BERT, kmeans, DLRM and llama_cpp have no completed results in the inspected trial/recovery summaries and are excluded. A saved “running” status does not establish that a process is currently alive.', '',
'Native application results below use one consistent perf group (stdout_core_cache.log) across five successful campaign repetitions. They are means of five reported results, not a pool of all six profiler-group executions. Native memory_pilot has three exploratory folders and only a checksum in its application output. Simulator results are one smoke run each.', '',
'| Workload | Native input | Simulator input | Application observation |',
'|---|---|---|---|',
'| memory_pilot | 512 MiB, 8 passes | 1 MiB, 8 passes | Both emit a checksum; no comparable application timer |',
'| STREAM | 50,000,000 doubles/array × 3 = 1.2 GB; 20 iterations; 8 threads | 65,536 doubles/array × 3 = 1.5 MiB; 3 iterations; 1 thread | Simulator timer too coarse for valid kernel bandwidth |',
'| pointer_chase | 512 MiB; requested n=5; 500 ms sampling interval; 1 worker | 2 MiB; requested n=1; 10 ms sampling interval; 1 worker | Different cache and sampling regimes |',
'| ANN | 200,000 vectors × 128 dimensions; 1,000 queries; top-10 | 1,024 vectors × 128 dimensions; 8 queries; top-10 | Same HNSW driver algorithm/settings, different database and concurrency |', '',
'Native machine: i7-12700, 25 MiB L3. Simulator: one TimingSimpleCPU, approximately 2.4 GHz, 2 MiB L2 and 96 MiB L3, 8 GiB CXL endpoint, node-1 allocation. Native ANN is permitted CPUs 0–15; its campaign command does not explicitly fix its OpenMP thread count. Do not assume it ran with exactly eight threads.', '',
'| Application metric | Native mean ± sample SD (5 reps) | Simulator output | Interpretation |',
'|---|---:|---:|---|']
for kernel in ['Copy', 'Scale', 'Add', 'Triad']:
    v = native['stream'][kernel + '_GBps']
    val = {'Copy':'inf', 'Scale':'1.0487', 'Add':'inf', 'Triad':'1.5745'}[kernel]
    lines.append(f'| STREAM {kernel} GB/s | {v["mean"]:.4f} ± {v["sample_std"]:.4f} | {val} | Reject simulator kernel rate: ~1 ms timer resolution |')
v=native['pointer_chase']['ns_per_dereference']
lines.append(f'| Pointer dereference ns | {v["mean"]:.4f} ± {v["sample_std"]:.4f} | 7.437 | Not CXL transaction latency; cache hits and timing/sampling affect it |')
v=native['ann']['QPS']
lines.append(f'| ANN queries/s | {v["mean"]:.2f} ± {v["sample_std"]:.2f} | 2,667.0721 | Apparent {v["mean"]/2667.0721:.2f}× throughput gap, **not attributable to CXL** |')
for metric, val in [('BUILD_TIME_SEC',0.290956),('SEARCH_TIME_SEC',0.003)]:
    v=native['ann'][metric]
    lines.append(f'| ANN {metric} | {v["mean"]:.6f} ± {v["sample_std"]:.6f} | {val:.6f} | Different amounts of work; guest search lasts only ~3 ms |')
lines += ['', 'The 7.437 ns pointer result is not evidence that CXL beats native DRAM. It is much shorter than the ~300 ns observed CXL reads and uses a 2 MiB buffer. Cache-resident chasing can coexist with CXL traffic from allocation, initialization and other activity in the process-wide phase. The existing markers do not isolate the chase loop.', '',
'**CXL measurements, scoped to the completed workload phase.** Latency runs from the host-facing CXL boundary to its returning response, excluding CPU/cache lookup time. Tick frequency is 10¹² Hz, so 1,000 ticks = 1 ns. Bandwidth is transferred CXL payload divided by simulated phase time; it is not STREAM algorithmic bandwidth.', '',
'| Workload | Phase seconds | Read requests | Read MiB | Mean GB/s | Mean ns | P50 ns | P95 ns | P99 ns |',
'|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for w,s in sim.items():
    m=s['cxl_metrics']; l=s['latency_ns']['read_latency_ticks']
    lines.append(f'| {w} | {s["phase_seconds"]:.6f} | {m["cxl.read_requests"]:,} | {m["cxl.read_bytes"]/2**20:.3f} | {m["cxl.read_bandwidth_GBps"]:.5f} | {l["mean"]:.2f} | {l["p50"]:.2f} | {l["p95"]:.2f} | {l["p99"]:.2f} |')
lines += ['', 'All four phases record zero CXL writes. This does not mean the applications performed no stores: stores may stay in caches and writebacks can occur outside the phase. These runs do not characterize write throughput or bidirectional performance.', '',
'| Workload | Fabric ns | Device enqueue-to-start ns | Device service ns | Return ns | Non-service share of mean |',
'|---|---:|---:|---:|---:|---:|']
for w,s in sim.items():
    l=s['latency_ns']; vals=[l['latency.'+k]['mean'] for k in ['fabric','queue','device','return_path']]
    total=l['read_latency_ticks']['mean']; assert abs(sum(vals)-total)<1e-6
    lines.append(f'| {w} | {vals[0]:.2f} | {vals[1]:.2f} | {vals[2]:.2f} | {vals[3]:.2f} | {100*(total-vals[2])/total:.1f}% |')
lines += ['', 'Fabric plus return contributes about 148–149 ns per read; all non-service components contribute about 165 ns. This is modeled path cost, **not an incremental penalty relative to native DRAM**: the local path also has latency, and no matched measurement exists. Device service includes backend scheduling. The ~16 ns enqueue-to-start component includes modeled protocol/scheduling delay, so it is not all saturation-induced waiting. Component means sum to total; individual percentiles need not sum.', '',
'| Workload | Endpoint queue-full events | Endpoint backpressure cycles | Mean endpoint request depth | P99 depth | Max depth | Modeled upstream port read utilization |',
'|---|---:|---:|---:|---:|---:|---:|']
for w,s in sim.items():
    m=s['cxl_metrics'];q=m['cxl.endpoint.0.queue_depth']
    lines.append(f'| {w} | {m["cxl.endpoint.0.queue_full_events"]:,} | {m["cxl.endpoint.0.backpressure_cycles"]:.1f} | {q["mean"]:.5f} | {q["p99"]} | {q["max"]} | {100*m["cxl.link.1.read_utilization"]:.3f}% |')
lines += ['', 'Queues show short bursts, not sustained saturation in these phase averages. Queue-full events count rejected admission attempts and do not equal a count of distinct blocked requests. The upstream-port utilization denominator is the modeled 16-byte crossbar width / 417 ps clock (38.37 GB/s per direction), not a verified physical CXL link capacity. Endpoint bandwidth and physical link width/speed are unspecified: endpoint utilization and oversubscription remain unknown. A low average does not rule out brief bottlenecks.', '',
'**Native PMU context, not direct counter equivalence.**', '',
'| Workload | Native IPC | Native generic cache misses / 1,000 instructions | Native cycles-with-outstanding-data-read fraction | Simulator IPC, whole timing interval |',
'|---|---:|---:|---:|---:|']
for w in native:
    d={r['metric']:float(r['mean']) for r in pmu if r['workload']==w}
    lines.append(f'| {w} | {d["ipc"]:.4f} | {d["cache_misses_per_million_inst"]/1000:.3f} | {100*d["offcore_outstanding_fraction"]:.2f}% | {sim[w]["stats"]["board.processor.switch.core.ipc"]:.4f} |')
lines += ['', 'These native fractions indicate frequent outstanding reads, not the fraction of execution stalled on memory and not a direct MLP count. Generic native cache-misses are not automatically equivalent to gem5 L3 demand misses. Native memory_traffic.csv records core mem-loads/mem-stores events, not memory-controller transferred bytes; zero mem-loads must not be interpreted as zero memory traffic. The saved data does not provide a validated matching native per-request memory-latency histogram or DRAM GB/s measurement for these CXL counters.', '',
'**What this says about CXL:** the strongest observed cost is request-path latency and its tail (~0.60–0.63 µs P99), with brief admission backpressure. The current successful runs do not demonstrate a CXL bandwidth ceiling, a write bottleneck, or an endpoint-imbalance problem (there is only one endpoint). ANN has an observed application throughput gap, but attributing it to CXL would be unsupported.', '',
'For a causal comparison, run identical inputs, binaries, CPU/cache configuration and ROI twice inside SimCXL, changing only local-memory versus CXL placement. Compare simulated ROI time and application throughput; inspect actual placement and traffic, and make the working set exceed the relevant cache when testing memory. Native runs with the same inputs remain useful context but do not isolate the CXL effect. Repair the guest timing/ROI measurements before using short STREAM/ANN kernels for performance conclusions. No new runs were launched for this report.', '',
'**Provenance:** simulator source commit 8304d434fdc9c9a4c0a194c3a2a82f0f599686ae; original trial 20260903-065341. Native campaign files are dated 2026-09-01. The companion comparison.json contains numeric observations, selected native repetition values, compact CXL metrics, metadata and SHA-256 hashes of all data files read. compare.py reproduces the report while these source paths remain available. Native and simulator application times, simulator host execution time, and CXL transaction latency are distinct measurements; the ~600× host/sim-time ratio is not a CXL penalty.', '']
(OUT/'README.md').write_text('\n'.join(lines))
print('\n'.join(lines[:34]))
