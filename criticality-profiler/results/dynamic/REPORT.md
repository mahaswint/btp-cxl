# Dynamic tiering results

PAC now updates during execution and controls adaptive-bin promotions and
LRU demotions. Both managed policies pay the same assumed page-copy cost.
The frequency comparison uses the same adaptive policy with miss counts.

See [DYNAMIC_MODEL.md](../../DYNAMIC_MODEL.md) for the model, assumptions,
reproduction, and differences from the PACT implementation.

All cases assume 80 ns DRAM, 250 ns CXL, 16 outstanding-memory slots,
10 GB/s migration throughput, and 1000 ns fixed overhead per moved page.
Copies pause the workload; this is not background Linux migration.

| Case | All-CXL ms | All-DRAM ms | Frequency ms | PAC ms | PAC reduction | PAC promotions/demotions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pilot | 3.952 | 1.297 | 4.285 | 4.422 | -3.187% | 250/250 |
| mcf_long20ms | 46.967 | 15.436 | 37.748 | 37.748 | +0.000% | 22/22 |
| mcf_long1ms_reserve8 | 46.967 | 15.436 | 41.188 | 39.830 | +3.297% | 875/883 |
| lbm_short200us | 1.313 | 0.498 | 1.865 | 1.606 | +13.906% | 121/121 |
| xalancbmk_short200us | 1.693 | 0.659 | 1.697 | 1.674 | +1.329% | 38/38 |

The long runs use 12 million instructions following 200k cache-warmup
instructions. Other runs use 1 million instructions following the same warmup.
The 20 ms long run uses 256 DRAM pages with no extra reserve. The 1 ms long
stress run uses 256 DRAM pages and an 8-page eager reserve. Short runs use
64 DRAM pages and 200 us windows. Shorter windows are sensitivity tests,
not the paper's default sampling interval.

The 20 ms run ties because both policies choose the same first promotion
batch and the workload finishes before the next update. Faster sampling
exercises repeated runtime adaptation and exposes migration churn.

A positive comparison against dynamic frequency does not necessarily mean
tiering beats leaving the workload on CXL. In particular, inspect the lbm
stress case against its all-CXL reference: less churn helps PAC relative to
frequency, while migration still costs more than placement saves.

Migration accounting, capacity/reserve bounds, tier-load conservation, and
decision timestamps were validated. Unit tests cover dependencies, causal
sampling, repeated updates, adaptive bins, cold-page selection, migration
costs, disabled migrations, and zero-capacity controls.
