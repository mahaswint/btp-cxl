# Designed variable-MLP streams: PAC versus frequency

Synthetic, pre-filtered LLC-miss streams. This tests PACT-inspired scoring and our lightweight policy; it is not a reproduction of the paper's hardware speedup. Only the explicitly selected scenario is run; see the full-suite report for controls.

Decay alpha = 0.503 for both PAC and frequency: `score_new = alpha * score_old + window_contribution`. Observation window = 20 ms. All tracked scores decay once per observation, including empty CXL windows.

| Scenario | Frequency ms | PAC ms | Runtime reduction | Promotions F/P | Critical pages in DRAM F/P | Updates F/P |
|---|---:|---:|---:|---:|---:|---:|
| hot_first_mlp16 | 1049.681261 | 829.060461 | 21.017885% | 1024/1024 | 128/768 | 52/41 |

Parameters: 90/190 ns DRAM/CXL service (nominal service latency also used as constant k), 20.000000 ms observations, 1,024-page DRAM (4 MiB), two 1,024-page active groups (8 MiB), and identical cold warmup residency. Hot pages have exactly four times as many load misses. Each scenario alternates 12 copies of each phase. Dependencies create the overlap: chain width 1, hot batch width 1/2/4/8/16. Per-tier MLP is calculated from outstanding-load occupancy and active time, never supplied to the scoring function.

Both policies share the bounded-bin policy, reservoir seed, batch cap (128), LRU approximation, and preset total budget of 1,024 promotions. Copying costs 1,409.6 ns per moved page and pauses execution. Once the fixed budget is exhausted, placement stops changing but execution and periodic observations continue. Equal actual promotions, demotions, copy costs and load conservation are checked. Independent analytical checks cover serial, parallel, repeated-cycle, partial-batch and mixed-tier timing. The MLP=1 control must match exactly; reversing the phase order is also retained.

Requests enter after cache filtering: every listed request is assumed to be an LLC miss. No cache-hit rate, CPU instruction count, prefetcher, bandwidth contention or hardware sampling loss is inferred. The independent batches and assumed service times form an analytical workload. The batch barrier is part of that workload, not a simulated CPU pipeline. This makes the phase-level criticality mechanism visible under controlled assumptions. It does not prove that every real workload benefits or that the complete PACT runtime is reproduced.

All source workloads are in [streams.csv](streams.csv); measured decisions and MLP are in the window CSVs. Positive runtime reduction is 100 * (frequency_time - PAC_time) / frequency_time.

Wall seconds: 5.828116.
