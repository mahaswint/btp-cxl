# PAC decay 0.7 on variable-overlap bc-twitter

48M continuous instructions, 200k warmup, half observed page footprint in DRAM.
Legacy policy settings retained to isolate decay: 64-page batches, exact page observations, 90/190 ns tiers.
PAC retention is per update: score = decay * old_score + new_attribution. Frequency is unchanged in the requested experiment.
Both-decay controls distinguish recency from the MLP scoring signal. 0.2 ms is an explicitly short-window sensitivity case.
Workload screening used fixed first-touch placement, no migrations, 0.2 ms windows, and at least 100 CXL misses per qualifying window.
Selection favored the longer bc-twitter recording with 391 qualifying windows and a 1.0–5.43 MLP range; mcf also had substantial variation.
Model observations are not hardware measurements. No trace looping or concatenation was used.

| Window ms | Comparison | Frequency ms | PAC ms | Reduction | Frequency/PAC promotions | PAC MLP range |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 5 | no_decay | 107.232566 | 106.312708 | +0.8578% | 522/172 | 1.958–4.393 |
| 5 | pac_decay_07 | 107.232566 | 106.852599 | +0.3543% | 522/390 | 2.383–4.396 |
| 5 | matched_decay_07 | 107.034782 | 106.852599 | +0.1702% | 453/390 | 2.383–4.396 |
| 1 | no_decay | 108.857191 | 106.671491 | +2.0079% | 1107/327 | 2.328–5.337 |
| 1 | pac_decay_07 | 108.857191 | 107.317875 | +1.4141% | 1107/552 | 2.328–5.352 |
| 1 | matched_decay_07 | 107.454461 | 107.317875 | +0.1271% | 599/552 | 2.328–5.352 |
| 0.2 | no_decay | 116.520521 | 115.513501 | +0.8642% | 3890/3522 | 1.000–5.467 |
| 0.2 | pac_decay_07 | 116.520521 | 108.224759 | +7.1196% | 3890/868 | 1.000–5.456 |
| 0.2 | matched_decay_07 | 108.257751 | 108.224759 | +0.0305% | 880/868 | 1.000–5.456 |

All cases passed load conservation, migration-count/cost, capacity and decision-time checks.
The unchanged-frequency results are identical across PAC-decay/no-decay pairs.
Scores and historical reservoir entries cool consistently; empty-observation windows also cool existing scores.
Migration counts are natural and not forced equal. Copy overhead can dominate differences.
These are analytical results and do not validate the complete PACT/Linux system.
Details: [results.json](results.json), workload selection: [workload_screen.json](workload_screen.json).
