# Random decay sensitivity: 20 ms only

Six random alpha values were drawn before outcomes using seed 20261013: 0.619, 0.264, 0.847, 0.874, 0.379, 0.503. Each alpha is fixed throughout its run. Alpha 0.7 and 1.0 are fresh reference runs. Both PAC and frequency receive the same alpha. Every case uses the same synthetic streams, 12 rounds, 25,313,280 loads, 90/190 ns service times and 4 MiB DRAM.

| Alpha | Kind | MLP 8 runtime reduction | MLP 16 runtime reduction | PAC serial pages in DRAM, MLP 8/16 |
|---|---|---:|---:|---:|
| 0.264 | random | +2.788678% | +9.230026% | 384/640 |
| 0.379 | random | +2.947430% | +13.160996% | 384/640 |
| 0.503 | random | +7.857023% | +21.017885% | 512/768 |
| 0.619 | random | +7.481444% | +24.162138% | 384/768 |
| 0.700 | reference | +7.481444% | +24.162138% | 384/768 |
| 0.847 | random | +7.481444% | +28.140921% | 384/896 |
| 0.874 | random | +7.481444% | +28.140921% | 384/896 |
| 1.000 | reference | +4.899196% | +23.946698% | 256/768 |

Positive reduction favors PAC. Every case actually reaches 1,024 promotions and 1,024 demotions for each policy, with equal 2.886861 ms copy charges. Placement freezes after that preset budget is exhausted. All outcomes are retained; this is parameter sensitivity, not independent stochastic trials or a confidence interval.

The shared policy source now decays histogram reservoir values as well as tracked page scores. These fresh references use that same build. Historical alpha<1 reports used the earlier reservoir behavior and should not be directly combined with this sweep. Source snapshots and checksums are retained.

Constant-MLP controls at the minimum/maximum random alpha and alpha 0.7 matched exactly in runtime and placement. Analytical timing, decay, workload identity, load conservation, observation spacing, capacity and equal migration checks passed.

Synthetic LLC-miss streams and analytical batch execution demonstrate the scoring mechanism under controlled assumptions. They do not reproduce the complete PACT runtime or the paper's hardware results.

[All runtimes and counts](summary.csv) · [Detailed measurements](measurements.json) · [Preselected run plan](plan.json) · [Source/build provenance](provenance.json)

Completed 19 cases in 170.22 wall seconds.
