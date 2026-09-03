# Only workloads-full provisions an image; only build compiles gem5.
PYTHON ?= python3
JOBS ?= 2
ARGS ?=
PREPARE_ARGS ?=
SIMCXL_ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
.PHONY: help build workloads workloads-all workloads-full workloads-dry-run workloads-smoke workloads-trial

help:
	@echo 'make workloads          Run all workloads installed in the prepared image'
	@echo 'make workloads-all      Require and run all eight supported workloads'
	@echo 'make workloads-full     Prepare the all profile, then run all eight workloads'
	@echo 'make workloads-dry-run  Validate and print the workload commands'
	@echo 'make workloads-smoke    Run smaller inputs in a separate result directory'
	@echo 'make workloads-trial    Sample each smoke workload for up to 45 minutes'
	@echo 'make build              Build gem5 explicitly (JOBS=2 by default)'
	@echo 'Options: make workloads ARGS="--cores 2 --repeat 3 --keep-going"'

build:
	cd "$(SIMCXL_ROOT)" && scons --ignore-style build/X86/gem5.opt -j$(JOBS)

workloads:
	$(PYTHON) "$(SIMCXL_ROOT)guest/run_all.py" $(ARGS)

workloads-all:
	$(PYTHON) "$(SIMCXL_ROOT)guest/run_all.py" --suite all $(ARGS)

workloads-full:
	$(PYTHON) "$(SIMCXL_ROOT)guest/setup.py" ensure-all --jobs $(JOBS) $(PREPARE_ARGS)
	$(PYTHON) "$(SIMCXL_ROOT)guest/run_all.py" --suite all $(ARGS)

workloads-dry-run:
	$(PYTHON) "$(SIMCXL_ROOT)guest/run_all.py" --dry-run $(ARGS)

workloads-smoke:
	$(PYTHON) "$(SIMCXL_ROOT)guest/run_all.py" --size smoke --keep-going $(ARGS)

workloads-trial:
	$(PYTHON) "$(SIMCXL_ROOT)guest/run_all.py" --size smoke --trial-minutes 45 --keep-going $(ARGS)
