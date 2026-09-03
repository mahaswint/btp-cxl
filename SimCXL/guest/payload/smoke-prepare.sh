#!/usr/bin/env bash
# Executed during fast boot, before timing/phase measurement, in the COW disk.
set -euo pipefail
cd /opt/btp
mkdir -p smoke/bin
case "$1" in
    stream)
        gcc -O2 -march=x86-64 -fopenmp -DSTREAM_ARRAY_SIZE=65536 -DNTIMES=3 \
            upstreams/stream/stream.c -o smoke/bin/stream ;;
    ann)
        g++ -std=c++2a -O2 -march=x86-64 -fopenmp -Iupstreams/faiss smoke/src/ann_benchmark.cpp \
            build/faiss/faiss/libfaiss.a -lopenblas -llapack -o smoke/bin/ann_benchmark ;;
    pointer_chase)
        cp -a upstreams/pointer_chase smoke/pointer_chase
        # Pinned multichase has a fixed half-second sampling interval; shorten
        # only the overlay copy, keeping the pointer-chasing implementation.
        grep -q '^#define DELAY_USECS 500000$' smoke/pointer_chase/multichase.c
        sed -i 's/^#define DELAY_USECS 500000$/#define DELAY_USECS 10000/' smoke/pointer_chase/multichase.c
        make -C smoke/pointer_chase -j1 multichase
        cp smoke/pointer_chase/multichase smoke/bin/multichase ;;
esac
