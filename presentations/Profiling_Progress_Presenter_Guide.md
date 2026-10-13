## Slide 1: CXL memory profiling and criticality-based placement

Today I will explain how our profiling work developed, what the workloads taught us, and how the current architecture uses memory-level parallelism to choose pages. Our main result is a 23.95% reduction in modeled runtime on a controlled synthetic MLP-16 workload. With score decay, it reaches 24.16%. I will distinguish those mechanism experiments from native measurements and real-trace replay results.



## Slide 2: The question behind our profiling work

Fast DRAM has limited capacity. We want to place the pages whose access delays matter most to runtime in DRAM, while leaving less critical pages in CXL memory.

Access frequency tells us how often a page appears. It does not tell us how much of that page’s latency overlaps other memory requests or useful computation.

Our work tests whether an MLP-weighted page score makes better placement decisions than frequency when both policies share the same capacity and migration rules.

The presentation separates measured native behavior, modeled replay of public traces, and controlled synthetic experiments that expose the scoring mechanism.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/README.md

## Slide 3: What we have completed so far

We archived native profiling runs, workload launchers, machine settings, processing scripts and derived results. Seven workload families have five-run summaries.

We built analytical profilers for counterfactual criticality, trace dependency slack, static PAC scoring and continuous PAC-driven migration.

We added streaming execution and a compact memory-event cache so longer public traces can be compared without repeatedly decoding the raw instruction stream.

We audited PACT data and policy differences, retained real-trace controls, and designed variable-MLP streams that demonstrate more than 20% modeled improvement.

Source: https://github.com/mahaswint/btp-cxl/blob/main/README.md

## Slide 4: Profilers and execution models evaluated

These are the documented profiling approaches and our implementations. Native Linux perf is the confirmed hardware tool. The remaining rows are analytical engines we built and evaluated. We should not describe unrecorded tools such as VTune as completed experiments. The synthetic path and compact path share policy logic, while their execution abstractions differ.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/README.md

## Slide 5: Native profiling setup and collection

The recorded machine uses an Intel Core i7-12700 with 20 logical CPUs. Each run records the command, CPU affinity, kernel, governor and counter permissions.

The profiling script runs six counter groups: core/cache, memory traffic, top-down memory bound, top-down backend bound, retired memory and TLB walks.

We keep raw counter files, workload output and a return code for every group. The archive contains 54 run directories, including failed or partial attempts.

Derived metrics use cycles and instructions from the same counter group. Five repetitions per summarized workload let us inspect variation rather than rely on one run.

Sources: https://github.com/mahaswint/btp-cxl/blob/main/NativePC/README.md
https://github.com/mahaswint/btp-cxl/blob/main/NativePC/scripts/process_native_campaign.py
https://github.com/mahaswint/btp-cxl/blob/main/NativePC/system_info/system_baseline.txt

Source: https://github.com/mahaswint/btp-cxl/blob/main/NativePC/scripts/run_native_profile.sh

## Slide 6: Native workload coverage

We profiled seven workload families, with five runs for each summary. Pointer chase and STREAM form the memory-heavy end of the table. The model workloads cover inference, embeddings, clustering and neighbor search. The third column is IPC, and the final column is retired L3 load misses per million instructions. This compares their native behavior, without claiming that any row already achieved a CXL speedup.

Source: https://github.com/mahaswint/btp-cxl/blob/main/NativePC/processed_data/workload_summary.csv

## Slide 7: What the native counters tell us

Pointer chase and STREAM show very low IPC and many retired L3 load misses. They give us useful examples of strongly memory-sensitive behavior.

llama.cpp has more L3 misses than the other summarized ML workloads. DLRM also shows memory activity and motivated separate phase-level instrumentation.

Outstanding-read cycle fractions reach about 0.951 for pointer chase and 0.981 for STREAM. These indicate time with requests outstanding, not the average number of concurrent requests.

We therefore cannot call a native workload “high MLP” from this fraction alone. PAC requires occupancy divided by active time, which our analytical engines measure explicitly.

Source: https://github.com/mahaswint/btp-cxl/blob/main/NativePC/processed_data/workload_summary.csv

## Slide 8: Counter interpretation and targeted checks

We distinguish counter scheduling coverage from the workload metric. A counter running for 99% of the measurement does not mean page walks occupy 99% of runtime.

The targeted DLRM run reports load page-walk activity of 1.302% and store page-walk activity of 2.042% of measured cycles.

The exact combined load/store activity cannot be recovered from these aggregate counters. Its union lies between 2.042% and 3.344%, depending on overlap.

The same principle motivates criticality profiling: adding events or counting misses does not reveal which delays overlap and which delays extend execution.

Source: https://github.com/mahaswint/btp-cxl/blob/main/NativePC/raw_data/dlrm/native_pw/20260924_172101_dlrm_pw/summary.txt

## Slide 9: Simulator evaluation and the OCEAN baseline

The repository preserves SimCXL and OCEAN work. We tested OCEAN’s direct memory-server path against an equivalent local-memory loop before a planned PIPM prototype.

Median OCEAN/native ratios were 298.82× for 64 B requests, 19.70× for 4 KiB requests and 7.63× for 64 KiB requests, with five repetitions per configuration.

That test exposes synchronous loopback TCP overhead and the importance of request batching. It is a data-path microbenchmark, rather than an application slowdown result.

The audited QEMU backend allocates normal guest RAM and retains server metadata without forwarding guest memory operations. The baseline does not validate a full guest CXL path.

Source: https://github.com/mahaswint/btp-cxl/blob/main/experiments/ocean-runtime-baseline-2026-09-29/README.md

## Slide 10: Early criticality and public trace experiments

The first phase/lane model computes a page’s benefit by replaying the workload with only that page moved to fast memory. It gives a 15% win in an overlap example.

The serial control ties frequency. A joint-bottleneck counterexample loses 39.13%, because scoring pages individually misses the benefit of promoting two pages together.

The instruction-trace pilot adds register dependencies, cache filtering and held-out evaluation using public SPEC traces: mcf, lbm and xalancbmk.

The slack-based sweep shows mixed, small gains. mcf ranges from −2.376% to +1.919%, lbm from 0% to +1.502%, and the selected xalancbmk region ties throughout.

Also see https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/README.md. Explain that counterfactual replay is an offline diagnostic. Slack scoring is a separate heuristic from PAC. These results are modeled held-out comparisons, not native application speedups.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/REPORT.md

## Slide 11: PAC scoring and memory-level parallelism

Memory-level parallelism, or MLP, is the average number of outstanding demand-load requests while a tier has at least one such request active.

For each tier and observation window: MLP = outstanding-request occupancy area / active time. Estimated stall cost = k × load misses / MLP.

We attribute that cost to pages in proportion to their observed load misses. The accumulated score becomes PAC_new = alpha × PAC_old + new page contribution.

A miss in a low-MLP window contributes more score than a miss in a high-MLP window. Within one tier and one window, PAC remains proportional to page frequency.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/PACT_MODEL.md

## Slide 12: Frequency and PAC in a controlled example

The serial group has one relative miss at MLP one, so its relative score is one. The hot group has four misses but MLP sixteen, so its relative score is only one quarter. Frequency sees four versus one and chooses the hot group. PAC sees the difference in overlap and can prioritize the serial group. This distinction appears across windows, because attribution within any one tier and window is still proportional to frequency.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/SYNTHETIC_STREAMS.md

## Slide 13: Dynamic placement and fair policy comparison

The dynamic engine starts both policies with the same first-touch placement. It updates scores during a continuous execution region using only requests observed so far.

At an update, high-score CXL pages become promotion candidates. The policy demotes least-recently-observed DRAM pages to make room and respects capacity and batch limits.

Frequency and PAC share binning, sampling seed, first-touch placement, demotion and copy costs. Their scoring signal differs: miss count versus MLP-weighted contribution.

Every promotion and demotion incurs an assumed cost. Copies pause modeled execution, so reduced runtime can reflect page selection, migration timing or reduced migration churn.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/DYNAMIC_MODEL.md

## Slide 14: Final analytical architecture

This diagram shows the implemented analytical evaluation architecture. It is not a deployed hardware PIPM or complete PACT/Linux runtime. The compact trace engine and designed synthetic engine feed the shared RuntimePolicy. Only requests observed before the decision time can update the policy. Moving a page changes later modeled service and measured overlap.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/COMPACT_MODEL.md

## Slide 15: Why we added the compact execution path

Repeated raw instruction replay became expensive. The compact engine preprocesses the trace once into memory requests, weighted dependencies, compute gaps and epoch fences.

For the available BC-kron region, 999.8 million measured instructions become a 405.2 MB event cache, compared with 64.0 GB of raw trace data.

The 5-million-instruction pilot took 0.659 s to preprocess and 0.061 s for four-policy replay. Against the previous 5.837 s pilot, first-run profiler acceleration is 8.11×.

This accelerates the profiling tool. It is separate from workload speedup. The compact model uses conservative 192-instruction epochs and omits pipelining between epochs.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/compact/REPORT.md

## Slide 16: Real-trace results and matched migration controls

The real BC-kron trace is a useful check on our assumptions. The legacy policy essentially ties. The all-events profile initially looks like a 2.13% improvement, but matching actual migration counts reduces it to 0.006%. The sampled profile slightly favors frequency. Measured CXL MLP remains near 1.3 even though the resource limit allows sixteen requests. This is why a high configured limit alone does not establish high observed parallelism.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/paper_aligned/REPORT.md

## Slide 17: Calibration and sensitivity evidence

The audited PACT public counter dataset contains 96 workload rows. On the emulated CXL tier, correlation with measured stall cycles rises from 0.829 for misses to 0.974 for misses/MLP.

The fitted CXL coefficient is 771.070 cycles, with leave-one-out mean absolute error of 39.69%. It supports MLP weighting while leaving substantial prediction error.

A continuous 48M-instruction BC-twitter prefix provides changing overlap. With 0.2 ms windows, PAC-only decay gives a 7.120% natural-policy improvement.

When frequency also uses decay, that case drops to 0.031%, with different natural migration counts. Recency and copy overhead explain much of the apparent advantage.

Additional source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/decay_07/REPORT.md. These are a calibration audit of published counters and analytical replay sensitivity tests. The coefficients are effective stall cycles, not service latency in nanoseconds.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/calibration/pact/REPORT.md

## Slide 18: High-MLP synthetic workload design

The active set contains a 4 MiB serial pointer-chain group and a 4 MiB independent-load group. The independent group has exactly four times as many load misses.

DRAM capacity is 4 MiB. Both policies start with the same cold warmup pages, so the active groups initially reside in CXL. The workload alternates both phases for 12 rounds.

Independent batch width varies across 1, 2, 4, 8 and 16. The main sequence starts with the hot group, and a separate MLP-16 case reverses phase order.

The model uses 90/190 ns DRAM/CXL service, 20 ms observations, 128-page batches and 1,024 total promotions. Both policies execute 25,313,280 load misses per case.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/SYNTHETIC_STREAMS.md

## Slide 19: Runtime reduction rises in the MLP-16 case

This chart shows every hot-first MLP setting at alpha one. Widths one, two and four tie. Width eight produces 4.90% less modeled runtime. Width sixteen produces 23.95%. The effect depends on overlap and on the policy decisions made before the migration budget runs out. These are deterministic designed streams with equal actual migration counts.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/REPORT.md

## Slide 20: The 23.95% result with equal actual copying

Here is the central comparison in absolute terms. Frequency takes 1093.201 milliseconds and PAC takes 831.416 milliseconds. Both complete 1024 promotions and 1024 demotions and pay the same 2.886861 milliseconds of copying. Frequency ends with none of the serial pages in DRAM, while PAC has 768. The reduction is 23.95%. Equal copying costs strengthen the comparison, although the policies can still migrate at different times.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/REPORT.md

## Slide 21: Phase order and score decay sensitivity

We kept the original settings and then tested score decay, shorter windows and reversed phase order. At twenty milliseconds, alpha 0.7 gives 24.16% at MLP sixteen. At ten milliseconds it gives 21.08%. Reversing phase order at alpha one still gives 21.43%. These historical decay runs predate the consistent reservoir-decay change in the following sweep. Shorter windows also make decay and promotion opportunities occur more frequently, so the changes cannot be attributed to observation precision alone.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/alpha_0_7/REPORT.md

## Slide 22: The full additional decay sweep

Six random alpha values were drawn before outcomes with seed 20261013. Alpha 0.7 and 1 are fresh references. Every run uses equal actual promotions, demotions and 2.886861 ms copy charges. The minimum and maximum random alpha and alpha 0.7 have exact constant-MLP controls. The shared policy now decays histogram reservoir values as well as page scores. Therefore earlier alpha below one reports should be presented as historical experiments, without pooling them into this sweep. The best reduction is 28.14% at alpha 0.847 and 0.874. The minimum is 9.23% at alpha 0.264. All outcomes are retained.
Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/random_decay_20ms/REPORT.md

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/random_decay_20ms/summary.csv

## Slide 23: Checks supporting the comparison

Every scenario preserves load-request count and DRAM capacity. Both policies must actually complete 1,024 promotions and 1,024 demotions, with equal copy costs.

The synthetic timing checks cover serial execution, independent batches, repeated cycles, partial batches and mixed-tier requests. Constant-MLP scoring must tie frequency.

The trace engines check cache filtering, demand-load attribution, store exclusion, causal dependency handling and decision timestamps. Streaming and full replay have equivalence checks.

We retain window MLP, per-page scores, final residency, migrations, configuration and all fixed scenarios. These records explain the mechanism behind the reported percentage.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/SYNTHETIC_STREAMS.md

## Slide 24: Implemented architecture and remaining deployment work

Implemented today: an analytical execution and policy stack with native archives, trace processing, causal score updates, migration accounting and controlled workload generation.

The synthetic result shows that MLP-weighted scoring can choose more useful pages under the declared assumptions. The available real-trace experiments show much smaller gains or ties.

A hardware deployment still needs verified tier counters, reliable per-page observations, real service and migration measurements, and a memory path that truly reaches CXL.

The next evaluation should compare an integrated runtime with frequency using representative applications, equal-resource controls and actual end-to-end timing, including profiling overhead.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/COMPACT_MODEL.md

## Slide 25: Progress and the result we can defend

We have a reproducible profiling workflow spanning native counters, multiple analytical profilers, public SPEC/GAP traces and designed workloads with explicit overlap.

The final analytical architecture combines observation, PAC scoring and shared promotion/demotion policy. It records the decisions and costs needed to explain each result.

Our central result is 23.95% less modeled runtime on the MLP-16 synthetic case, or 24.16% with alpha = 0.7. The reversed-order case gives 21.43%.

This establishes the scoring mechanism and motivates the next hardware experiment. It does not yet establish a 20% gain for the native ML applications or a complete PACT/PIPM deployment.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/REPORT.md