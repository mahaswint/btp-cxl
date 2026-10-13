# Full trace, lightweight model: 5 ms and 1 ms

999,800,000 measured instructions plus 200,000 cached warmup instructions.
Same prepared compact cache and half-footprint DRAM as the compact 20 ms comparison.
Natural adaptive comparison; migration counts are not forced equal.
Modeled times are approximate; exact observations and zero sampling processing cost remain assumptions.

| Window ms | Frequency modeled ms | PAC modeled ms | PAC reduction | Frequency/PAC promotions | Frequency/PAC updates | Actual run seconds |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 553.502148 | 553.496510 | +0.001019% | 110/108 | 110/110 | 52.04 |
| 1 | 555.946375 | 555.130249 | +0.146800% | 1009/724 | 553/553 | 183.28 |

Load conservation, capacity, decision timing, promotion/demotion counts and copy accounting passed.
Raw values, configuration and commands: [results.json](results.json).
