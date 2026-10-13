## Slide 1: Our task: criticality versus frequency profiling

We set out to compare two ways of choosing pages for limited DRAM capacity: access frequency and criticality-based access profiling using PAC.

Frequency ranks pages by how many slow-tier load misses they generate. PAC estimates how much those misses contribute to exposed memory stalls.

The question is whether PAC can keep the pages that matter most to execution in DRAM, especially when frequent accesses overlap through high memory-level parallelism.

We compare both policies with the same workload, memory capacity and migration rules. The current results come from our analytical simulator.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/PACT_MODEL.md

## Slide 2: Why PAC helps when memory accesses overlap

MLP is memory-level parallelism, the average number of outstanding demand-load requests during active memory time. Think of a serial group and an independent group. The hot group accesses each page four times as often, but at MLP sixteen those accesses overlap. Its relative stall contribution is four divided by sixteen, or one quarter. A serial page contributes one divided by one, or one. Frequency favors the hot page, while PAC can prioritize the serial page. PAC benefits from differences across observed windows, rather than from high MLP alone.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/SYNTHETIC_STREAMS.md

## Slide 3: 

We have two execution paths. Public traces pass through cache filtering and dependency construction, then the compact scheduler reuses those events. Our synthetic path generates known serial and independent miss batches. Both feed a shared policy. The observation layer measures demand-load misses, outstanding occupancy and active time. Frequency accumulates misses, while PAC weights them by observed MLP. The policy selects promotions, demotes cold pages and charges copies. Decisions only use observations available at the current time. This is our analytical architecture, with PIPM integration as the next implementation stage.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/COMPACT_MODEL.md

## Slide 4: Commands to build and run the comparisons

Run these commands from the repository root in a shell with a C++17 compiler and Python available. First enter criticality-profiler and compile the synthetic engine. The next two commands run the initial alpha-one cases for MLP eight and sixteen into separate demonstration folders. The third case demonstrates alpha 0.7. The Python script runs the complete fixed-seed decay sweep and generates its report. Running the script replaces its recorded sweep outputs, so copy any outputs you want to preserve first. No external trace download is necessary for these designed streams.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/SYNTHETIC_STREAMS.md

## Slide 5: PAC versus frequency on the available traces

The earlier trace experiments help us identify where PAC adds useful information. The short SPEC training segments fit into one twenty-millisecond window and tie frequency. A longer mcf run gives only a small difference at the displayed capacity. The full BC-kron matched-count comparison is also nearly a tie. BC-twitter offers changing overlap, but gains depend on policy and migration behavior. We can say PAC does not really shine in these recorded regions. That motivates a controlled experiment with much stronger differences in MLP across phases. These rows use different experiments and are not a common aggregate benchmark score.
Additional sources: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/paper_aligned/REPORT.md
https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/decay_07/REPORT.md

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/pac/REPORT.md

## Slide 6: The MLP 8 and MLP 16 workload design

We alternate two 4 MiB groups: a dependent pointer chain at MLP 1 and a hot group with four times as many misses, issued in independent batches of 8 or 16.

DRAM holds 4 MiB, while the active data totals 8 MiB. Both policies begin with the same cold pages in DRAM, so active pages initially access CXL.

Each case runs 12 rounds and 25,313,280 load misses. Service times are 90 ns for DRAM and 190 ns for CXL, with a 20 ms observation interval.

Both policies actually perform 1,024 promotions and 1,024 demotions and pay the same 2.886861 ms copy cost. Placement freezes after that budget is exhausted.

Requests are synthetic LLC misses. The model does not simulate CPU pipelines, prefetching or bandwidth contention. MLP is calculated from outstanding request occupancy, rather than supplied as a page criticality label.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/SYNTHETIC_STREAMS.md

## Slide 7: Initial results: MLP 8 and MLP 16

At alpha one, frequency takes 1217.408 milliseconds in the MLP-eight case, while PAC takes 1157.765, giving 4.90% less modeled runtime. At MLP sixteen, frequency takes 1093.201 milliseconds, while PAC takes 831.416, giving 23.95%. Frequency ends with zero serial pages in DRAM in either case. PAC ends with 256 in the first case and 768 in the second. Both use equal actual moves and identical copy charges. The MLP-one control ties exactly. Reversing phase order at MLP sixteen retains a 21.43% gain. These are synthetic modeled results, not measured application speedups.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/REPORT.md

## Slide 8: PAC versus frequency with varying score decay

Alpha is the fraction of the previous score retained at each twenty-millisecond update. We apply the same alpha to PAC and frequency. The fixed-seed sweep selected six random alpha values before seeing outcomes and added fresh alpha 0.7 and alpha-one references. With consistent decay of page scores and reservoir history, MLP sixteen reaches 24.16% at alpha 0.7 and 28.14% at alpha 0.847 or 0.874. Stronger forgetting at alpha 0.264 gives only 9.23%, so more aggressive decay is not automatically better. Actual copying remains equal in every row, and MLP-one controls tie. All displayed results come from this one sweep implementation.

Source: https://github.com/mahaswint/btp-cxl/blob/main/criticality-profiler/results/synthetic_streams/random_decay_20ms/REPORT.md

## Slide 9: Real applications and established benchmark examples

These examples pair familiar applications with established benchmark or software names.

Recommendations: product or ad ranking needs user and item features from embedding tables. DLRM is Meta's open recommendation model. With a batched implementation, different embedding rows can be fetched independently, so their memory misses can overlap. This is a configuration to measure, not a claim that every DLRM run has high MLP.

Database queries: joining orders with customers for sales analysis can be represented using TPC-H, a formal decision-support benchmark. A database engine that batches independent hash probes can keep multiple reads outstanding. The query plan and join implementation determine whether this opportunity becomes observed MLP.

Profile and session lookups: a service may retrieve many records for one request. RocksDB MultiGet batches keys, and its documentation explicitly describes pipelining Bloom-filter CPU cache misses to hide latency. For our memory-tiering experiment, keep the relevant dataset in memory and distinguish CPU memory overlap from disk I/O parallelism.

Graph analysis: social relationships or fraud connections form a graph. GAP Benchmark Suite provides BFS and PageRank kernels. Independent frontier or edge work can expose concurrent reads, although pointer dependencies can limit MLP. GAPBS represents graph kernels rather than a complete fraud application.

TPC-H is a benchmark standard. DLRM and GAPBS are benchmark workloads, while RocksDB is an established software system. They are not all formal industry standards. We propose these configurations because independent accesses can overlap, then verify actual MLP and differences between phases before asserting a PAC benefit.

Sources:
https://github.com/facebookresearch/dlrm/blob/main/README.md
https://arxiv.org/abs/1906.00091
https://tpc.org/tpch/
https://github.com/facebook/rocksdb/wiki/MultiGet-Performance
https://github.com/sbeamer/gapbs
https://neo4j.com/developer/demos/fraud-demo/
MLP opportunities for DLRM, TPC-H and graph configurations are architectural inferences, not benchmark measurements from our project.

## Slide 10: Tentative plan: validate PACT, then integrate PIPM

The plan has four stages. Stage one validates our PACT-inspired scoring and policy behavior. We check the equations, occupancy accounting, decay, page selection and migration costs against the paper and artifact, using serial controls and high-MLP cases. Its completion gate is a documented validated baseline and an explicit list of model differences. Stage two integrates that baseline with PIPM over two weeks after validation. In week one we connect observations, page identity and tier decisions. In week two we debug correctness, run the integrated PAC and frequency comparisons and record migration and timing effects. The gate is a working integrated prototype with repeatable results. These are tentative durations, not calendar deadlines.

Source: Repository work through 13 October 2026.

## Slide 11: Tentative plan: simulator selection and full evaluation

Stage three identifies a suitable simulator after the integrated behavior is defined. It needs to represent CPU memory overlap, DRAM and CXL behavior, contention and the cost of moving pages. We evaluate candidate compatibility with PIPM, workload support and feasible execution time. There is no deadline for this stage. Stage four performs the full simulation campaign and completes the project. We include high-MLP application candidates, serial controls, capacities, latencies and decay sensitivity, with consistent frequency comparisons. We record end-to-end performance and all profiling and migration overheads, then analyze results and prepare the final report. There is no deadline for this stage either.

Source: Repository work through 13 October 2026.