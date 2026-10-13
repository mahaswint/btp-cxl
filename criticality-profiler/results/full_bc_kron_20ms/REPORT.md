# Full available bc-kron trace, 20 ms updates

All 1,000,000,000 records in the public bc.kron-5154B member were consumed:
200,000 warmup plus 999,800,000 measured instructions. No truncation, repetition or concatenation.
The member is a representative recorded region, not a full multithreaded application execution.
DRAM: 262807 pages out of 525613 distinct accessed pages.
90/190 ns DRAM/CXL, 2.2 GHz core assumption, 20 ms update window, streaming execution.
Total wall time including download: 39.49 minutes. Hard cap: 60 minutes.

| Policy | Modeled runtime ms | Promotions | Demotions | Copy ms | Updates |
| --- | ---: | ---: | ---: | ---: | ---: |
| cxl | 513.807409 | 0 | 0 | 0.000000 | 0 |
| dram | 290.495211 | 0 | 0 | 0.000000 | 0 |
| frequency | 405.630579 | 54 | 54 | 0.152237 | 20 |
| pac | 405.630179 | 54 | 54 | 0.152237 | 20 |

PAC modeled runtime reduction versus frequency: +0.000098%.
This natural adaptive comparison does not enforce matched migration counts.
All four policies consumed the same measured instructions. Capacity, load conservation,
migration-count/cost and event-time validation passed. Simplified cache, single instruction
stream, synchronous migration and zero sampling-processing cost remain limitations.
