# Designed variable-MLP streams: PAC versus frequency

Synthetic, pre-filtered LLC-miss streams. This tests PACT-inspired scoring and our lightweight policy; it is not a reproduction of the paper's hardware speedup. All fixed scenarios and the control are retained.

| Scenario | Frequency ms | PAC ms | Runtime reduction | Promotions F/P | Critical pages in DRAM F/P | Updates F/P |
|---|---:|---:|---:|---:|---:|---:|
| hot_first_mlp1 | 2844.835161 | 2844.835161 | 0.000000% | 1024/1024 | 0/0 | 142/142 |
| hot_first_mlp2 | 1928.623581 | 1928.623581 | 0.000000% | 1024/1024 | 0/0 | 96/96 |
| hot_first_mlp4 | 1455.963341 | 1455.963341 | 0.000000% | 1024/1024 | 0/0 | 72/72 |
| hot_first_mlp8 | 1217.407821 | 1157.764621 | 4.899196% | 1024/1024 | 0/256 | 60/57 |
| hot_first_mlp16 | 1093.201261 | 831.415661 | 23.946698% | 1024/1024 | 0/768 | 54/41 |
| critical_first_mlp16 | 950.700761 | 746.979961 | 21.428488% | 1024/1024 | 384/1024 | 47/37 |

Parameters: 90/190 ns DRAM/CXL service (nominal service latency also used as constant k), 20 ms observations, 1,024-page DRAM (4 MiB), two 1,024-page active groups (8 MiB), and identical cold warmup residency. Hot pages have exactly four times as many load misses. Each scenario alternates 12 copies of each phase. Dependencies create the overlap: chain width 1, hot batch width 1/2/4/8/16. Per-tier MLP is calculated from outstanding-load occupancy and active time, never supplied to the scoring function.

Both policies share the bounded-bin policy, reservoir seed, batch cap (128), LRU approximation, and preset total budget of 1,024 promotions. Copying costs 1,409.6 ns per moved page and pauses execution. Once the fixed budget is exhausted, placement stops changing but execution and 20 ms observations continue. Equal actual promotions, demotions, copy costs and load conservation are checked. Independent analytical checks cover serial, parallel, repeated-cycle, partial-batch and mixed-tier timing. The MLP=1 control must match exactly; reversing the phase order is also retained.

Requests enter after cache filtering: every listed request is assumed to be an LLC miss. No cache-hit rate, CPU instruction count, prefetcher, bandwidth contention or hardware sampling loss is inferred. The independent batches and assumed service times form an analytical workload. The batch barrier is part of that workload, not a simulated CPU pipeline. This makes the phase-level criticality mechanism visible under controlled assumptions. It does not prove that every real workload benefits or that the complete PACT runtime is reproduced.

All source workloads are in [streams.csv](streams.csv); measured decisions and MLP are in the window CSVs. Positive runtime reduction is 100 * (frequency_time - PAC_time) / frequency_time.

Wall seconds: 50.577061.
