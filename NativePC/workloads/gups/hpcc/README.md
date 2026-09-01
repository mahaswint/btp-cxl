# HPC Challenge Benchmark Suite

This is a copy of the original [HPCC benchmark suite](http://icl.cs.utk.edu/hpcc/) source.

As per the [FAQ](https://icl.utk.edu/hpcc/faq/index.html#263), it is covered by the original BSD licence.

HPCC is not really one benchmark, but a collection of 7 benchmarks:

* [HPL](http://www.netlib.org/benchmark/hpl/) - the Linpack TPP benchmark which measures the floating point rate of execution for solving a linear system of equations.
* DGEMM - measures the floating point rate of execution of double precision real matrix-matrix multiplication.
* [STREAM](http://www.cs.virginia.edu/stream/) - a simple synthetic benchmark program that measures sustainable memory bandwidth (in GB/s) and the corresponding computation rate for simple vector kernel.
* [PTRANS](http://www.netlib.org/parkbench/html/matrix-kernels.html) (parallel matrix transpose) - exercises the communications where pairs of processors communicate with each other simultaneously. It is a useful test of the total communications capacity of the network.
* [RandomAccess](http://icl.cs.utk.edu/projectsfiles/hpcc/RandomAccess) - measures the rate of integer random updates of memory (GUPS).
* [FFT](http://www.ffte.jp/) - measures the floating point rate of execution of double precision complex one-dimensional Discrete Fourier Transform (DFT).
* Communication bandwidth and latency - a set of tests to measure latency and bandwidth of a number of simultaneous communication patterns; based on `b_eff` (effective bandwidth benchmark).

Although benchmarks such as HPL (used for the [top500](https://www.top500.org/) list) can be configured to run in a variety of different ways, it is most commonly configured to work on large square matrices (the largest that will fit in the available working memory).  Often benchmarkers will run HPL multiple times, however even if configured to run more than once, the default behaviour of HPCC is to record and report only the highest performance regardless of how different this may be from the other results.

## Coming soon ..

This copy is being modified to report all of its results in CSV format, with the output file name chosen either by the user or based on the reported name of the rank0 node, as reported by `MPI_Get_processor_name()`.  The output will include all recorded benchmark results, rather than just the best result from each benchmark.  The default output file name has already been altered, so that if you are running multiple copies of HPCC from the same source directory, they will output to different files provided that rank 0 in each case receives a different value from `MPI_Get_processor_name()`.  The input file is not yet customisable or unique.

It is assumed that the benchmark will be run multiple times with the same input, with each run of the benchmark appending to the CSV file if it already exists, or creating it if it does not.

Later, scripts will be added to assist in examining gathered results.  Most of these are aimed at comparing single node performance in order to track down problems on individual nodes within the supercomputer.
