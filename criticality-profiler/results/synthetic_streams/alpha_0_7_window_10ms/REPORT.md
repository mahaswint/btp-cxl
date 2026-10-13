# 10 ms windows, alpha = 0.7

Same synthetic hot-first streams, 12 rounds, 25,313,280 load requests per policy, 90/190 ns DRAM/CXL service, 4 MiB DRAM, 128-page per-update cap and total budget of 1,024 promotions. Both scores use decay 0.7. Previous 20 ms results are preserved.

| MLP | Frequency ms | PAC ms | PAC runtime reduction | Previous 20 ms reduction | Updates F/P |
|---|---:|---:|---:|---:|---:|
| 8 | 1209.937421 | 1113.950221 | 7.933237% | 7.481444% | 120/111 |
| 16 | 1088.588461 | 859.104461 | 21.080878% | 24.162138% | 108/85 |
| 1 | 2816.107461 | 2816.107461 | 0.000000% | 0.000000% | 281/281 |

Both policies actually perform 1,024 promotions and 1,024 demotions and incur 2.886861 ms of copy costs each. Stream identity, window spacing (including at most one batch of drain time), capacity, move counts and constant-MLP equality were checked. C++ analytical timing, decay and load conservation checks passed.

MLP 8 leaves 384 serial pages in DRAM under PAC, the same final count as with 20 ms, but migration timing changes. MLP 16 leaves 640 serial pages under PAC, down from 768 with 20 ms, and its runtime improvement falls. Frequency leaves zero serial pages in DRAM in both requested cases.

Alpha remains 0.7 per update, so decay happens twice as often in execution time. The unchanged 128-page per-update cap also doubles promotion opportunities per modeled second. Therefore this changes both observation granularity and the time scale of decay/promotion. Placement freezes after the same fixed total budget is exhausted.

These are controlled synthetic mechanism results; the workload and service assumptions were not retuned.

Details: [MLP 8](mlp8/REPORT.md), [MLP 16](mlp16/REPORT.md), [MLP 1 control](control/REPORT.md).
