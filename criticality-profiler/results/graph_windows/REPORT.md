# Continuous length and recalculation-window sweep

Same real bc-twitter region 876 prefix, 200k warmup, no looping or concatenation.
12M versus 48M runtime instructions; settings selected before measuring outcomes.
256 DRAM pages, 80/250 ns DRAM/CXL, 16 memory slots, 1 MiB cache, 64-page batches,
no eager reserve, 10 GB/s copying plus 1000 ns per moved page.
All windows except 20 ms are sensitivity experiments. Modeled runtime, not hardware measurements.

Positive reduction means PAC is faster than dynamic frequency.

| Instructions | Window ms | Frequency ms | PAC ms | Reduction | Frequency/PAC updates | Frequency/PAC copy ms | All-CXL ms | All-DRAM ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12M | 20 | 20.615 | 20.615 | +0.000% | 1/1 | 0.003/0.003 | 20.635 | 7.029 |
| 12M | 5 | 20.661 | 20.661 | +0.000% | 4/4 | 0.048/0.048 | 20.635 | 7.029 |
| 12M | 1 | 20.759 | 20.776 | -0.082% | 20/20 | 0.147/0.164 | 20.635 | 7.029 |
| 12M | 0.2 | 22.762 | 21.132 | +7.161% | 102/102 | 2.145/0.516 | 20.635 | 7.029 |
| 48M | 20 | 84.369 | 84.369 | +0.000% | 4/4 | 0.011/0.011 | 84.438 | 29.471 |
| 48M | 5 | 84.431 | 84.433 | -0.002% | 16/16 | 0.082/0.085 | 84.438 | 29.471 |
| 48M | 1 | 84.966 | 84.755 | +0.249% | 84/84 | 0.820/0.471 | 84.438 | 29.471 |
| 48M | 0.2 | 96.424 | 86.719 | +10.065% | 421/420 | 12.145/2.568 | 84.438 | 29.471 |

## Runtime-difference accounting

Positive values favor PAC. Residual is total savings minus copy and drain savings;
it captures the remaining execution difference, not a direct hardware stall measurement.

| Instructions | Window ms | Total saved ms | Copy saved ms | Drain saved ms | Residual saved ms |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 12M | 20 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| 12M | 5 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| 12M | 1 | -0.0171 | -0.0169 | +0.0001 | -0.0003 |
| 12M | 0.2 | +1.6301 | +1.6295 | +0.0001 | +0.0004 |
| 48M | 20 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| 48M | 5 | -0.0021 | -0.0028 | -0.0001 | +0.0008 |
| 48M | 1 | +0.2116 | +0.3496 | +0.0003 | -0.1383 |
| 48M | 0.2 | +9.7047 | +9.5768 | -0.0003 | +0.1282 |

Each case passed load-count conservation, capacity, decision-time, and migration accounting checks.
Full counts, drain times, provenance, and every outcome are in [campaign.csv](campaign.csv).
Sampling cost is zero in this analytical model; migration is synchronous and charged.
Faster than frequency need not mean faster than all-CXL. Longer execution within
one trace region still does not reproduce a full multithreaded application's phase mix.
