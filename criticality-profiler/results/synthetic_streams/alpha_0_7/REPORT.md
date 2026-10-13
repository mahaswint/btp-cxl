# Synthetic streams with alpha = 0.7

The same 12-round, hot-first inputs are replayed with `score_new = 0.7 * score_old + window_contribution` for both PAC and frequency. Decay applies every 20 ms observation to every tracked score, including empty CXL windows. Original alpha=1 results are preserved.

| MLP | Alpha=1 runtime reduction | Alpha=0.7 frequency ms | Alpha=0.7 PAC ms | Alpha=0.7 runtime reduction | Updates F/P |
|---|---:|---:|---:|---:|---:|
| 8 | 4.899196% | 1217.409421 | 1126.329621 | 7.481444% | 60/56 |
| 16 | 23.946698% | 1093.201261 | 829.060461 | 24.162138% | 54/41 |
| 1 | 0.000000% | 2844.843661 | 2844.843661 | 0.000000% | 142/142 |

Both policies actually perform 1,024 promotions and 1,024 demotions; copying is 2.886861 ms each. Each executes the same 25,313,280 load requests with 4 MiB DRAM and 90/190 ns assumed DRAM/CXL service. Placement still freezes when the preset total budget is exhausted. The MLP=1 control remains exactly equal. Analytical timing and decay checks passed.

MLP 8 ends with 0/384 serial pages resident in DRAM for frequency/PAC; MLP 16 ends with 0/768. At MLP 16 the final placement is unchanged from alpha=1, but migration timing differs. At MLP 8 decay also changes the final selection.

These remain controlled synthetic mechanism results. Input streams, latencies and migration budgets were not retuned.

Per-scenario outputs: [MLP 8](mlp8/REPORT.md), [MLP 16](mlp16/REPORT.md), [constant-MLP control](control/REPORT.md).
