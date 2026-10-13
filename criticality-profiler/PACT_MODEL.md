# PACT-inspired PAC experiment

This document describes the static PAC scoring experiment. The subsequent
[dynamic runtime extension](DYNAMIC_MODEL.md) adds online updates, adaptive
promotion, eager demotion, and migration costs in a separate executable.

The default `trace_profiler` metric is now `--criticality pac`. The previous
dependency-slack metric remains available with `--criticality slack`; its
results are preserved separately.

This implements the **PAC scoring equations**, with simulated observations.
It does not run the PACT userspace runtime, reproduce hardware counters, or
implement the paper's adaptive promotion and eager demotion migration policies.
Page placement remains an offline, equal-capacity, top-N comparison trained on
an earlier trace segment and held fixed on the held-out segment. The cache and
event timing model remain as described in [TRACE_MODEL.md](TRACE_MODEL.md): one
simplified data cache, explicit local DRAM latency, and CXL latency. Separate
L1/L2/LLC caches have not been added in this scoring change.

## Paper and equations

Source: [PACT: A Criticality-First Design for Tiered Memory](https://huaicheng.github.io/p/asplos26-pact.pdf),
sections 4.2–4.3, Equation 1 and Algorithm 1. [Authors' runtime](https://github.com/MoatLab/PACT).

For each tier `t` and sampling window `w`:

```
T1[t,w] = integral(outstanding demand-load requests to tier t over time)
T2[t,w] = time with at least one such request outstanding
MLP[t,w] = T1[t,w] / T2[t,w]
S[t,w] = k[t] * load_misses[t,w] / MLP[t,w]
Sp[p,w] = S[t,w] * page_load_misses[p,w] / load_misses[t,w]
PAC[p] = alpha * PAC[p] + Sp[p,w]
```

`k` in the paper is a calibrated tier coefficient, incorporating latency and
architectural effects. Here k defaults to the assumed tier latency (80 ns DRAM,
250 ns CXL). Consequently our scores are in modeled nanoseconds and have not
been calibrated to hardware stall cycles. Override with `--pac-k-dram-ns` and
`--pac-k-cxl-ns` to experiment with different coefficients.

The event replay emits a start/end interval for each demand-load cache miss.
Intervals are clipped into fixed **time** windows. Occupancy integrates all
overlapping intervals; active time is their union length. This emulates the
definition of TOR occupancy and active-time counters. A request crossing a
window contributes occupancy to both; its miss count and page attribution are
recorded once, at issue time. Real PACT uses hardware event-counter deltas and
PEBS records; their precise event timing is not reproduced here. The simulator
uses exact load-miss counts as noiseless samples, not probabilistic PEBS sampling.
Stores incur modeled latency but are excluded from this demand-load PAC stream.

Alpha defaults to 1 (accumulation, no cooling). Values from 0 to 1 are accepted.
All known scores decay at each represented window, including windows with no
new samples for that page. Request-free gaps also contribute elapsed-window
decay. A final partial window is included. No page score is updated from the
held-out evaluation trace.

The same tier decomposition supports mixed DRAM/CXL placements in the scoring
function and is tested. This experiment trains with all pages initially on CXL,
so its training profiles have CXL traffic only; it does not claim to exercise
mixed-tier online feedback. The configured maximum outstanding slots is a
resource bound; **measured MLP is calculated from occupancy**, not set equal to
that bound.

## Fair frequency comparison

In PAC mode both policies rank the same pages using the same **demand-load cache
miss domain**. Frequency uses training load-miss counts; PAC uses windowed,
MLP-weighted load-miss attribution. This avoids attributing policy differences
to one policy counting stores and the other counting loads. Slack mode retains
its original all-load/store-miss frequency domain.

Within one tier and one window, PAC is a constant times page miss frequency.
It cannot distinguish two pages' parallelism inside that window. PAC rankings
can differ over accumulated windows because a miss during a low-MLP phase costs
more than one during a high-MLP phase. This proportional-attribution limitation
is central to interpreting the experiment; graph slack is not substituted for
PACT's MLP formula.

## Run

```powershell
g++ -std=c++17 -O2 -Wall -Wextra -pedantic trace_profiler.cpp -o trace_profiler.exe
g++ -std=c++17 -O2 -Wall -Wextra -pedantic test_trace_profiler.cpp -o test_trace_profiler.exe
./test_trace_profiler.exe
./trace_profiler.exe --trace traces/605.mcf_s-1554B.champsimtrace.bin --out results/pac_custom --criticality pac --pac-window-ns 20000000 --capacities 16,64,256
python run_pac_campaign.py
python summarize_pac_results.py
```

The paper's 20 ms interval is the default (`20,000,000 ns`). The pilot trace
segments are often shorter than one such interval, so proportional attribution
will frequently collapse to frequency. The campaign also tests 20 us and 200 us
windows as **short-trace sensitivity experiments**, not paper-faithful intervals.
None of these window sizes is selected based on favorable results.

The sweep includes the existing three SPEC traces, 80 ns DRAM, CXL at 160/250/400
ns, 1/8/16 outstanding slots, and 0/16/64/256/1024 DRAM pages. The three window
sizes yield 405 comparisons. Original warmup/training/evaluation segmentation
is retained. All sources and prefix hashes remain in `traces/*.json`.

`results/pac/campaign.csv` contains outcomes. Per-run `_pac_windows.csv` exposes
misses, T1, T2, measured MLP, estimated stalls, and their page-attribution sum.
Other outputs contain page scores, placements, and full configuration. This
allows checking that attribution conserves each window's estimated stall total.

For a stronger PACT experiment, collect or replay longer regions spanning several
20 ms windows and add runtime promotion/demotion and migration cost. The current
comparison tests PAC scoring in isolation under assumed memory latencies.

An additional longer mcf experiment uses the same source trace, 200k warmup,
8 million training, and 4 million held-out evaluation instructions. It retains
20 ms windows, 80/250 ns DRAM/CXL, 16 memory slots, and alpha=1:

```powershell
python fetch_traces.py --records 12200000 --trace-name 605.mcf_s-1554B.champsimtrace.xz --output-dir traces/long
./trace_profiler.exe --trace traces/long/605.mcf_s-1554B.champsimtrace.bin --out results/pac/mcf_long20ms --train 8000000 --eval 4000000 --dram-ns 80 --cxl-ns 250 --pac-window-ns 20000000 --capacities 0,16,64,256,1024
python summarize_pac_results.py
```

The long prefix occupies 780.8 MB on disk in addition to the original prefixes.
Provenance is in `traces/long/*.json`. Its report includes the observed MLP for
each training window and held-out outcomes; see [PAC results](results/pac/REPORT.md).
