========================
Concepts & Architecture
========================

This page provides an overview of OCEAN's architecture and the core concepts behind
CXL memory emulation. Understanding these fundamentals will help you work effectively
with OCEAN and interpret experimental results.

What OCEAN Emulates
===================

OCEAN emulates CXL-based memory systems, providing:

* **Memory Devices** - Emulated CXL memory devices accessible through standard interfaces
* **Fabric Components** - CXL switches and fabric management
* **Multi-Host Access** - Multiple compute nodes accessing shared memory pools
* **Memory Coherence** - Coherent memory access across distributed hosts

OCEAN is designed to support research on CXL memory systems and is being developed
to support multiple CXL specifications as the standard evolves.

High-Level Architecture
=======================

OCEAN is composed of several key components that work together:

Core Simulation Components
--------------------------

**CXL Memory Simulation Library**
   The core emulation logic implementing CXL memory operations, cache coherence protocols,
   and performance modeling.
   
   * Located in ``src/`` directory
   * Compiled into ``libcxlmemsim.a`` static library
   * Provides the fundamental CXL emulation capabilities

**CXL Fabric Server**
   Manages the shared CXL memory fabric and coordinates access across multiple hosts.
   
   * Executable: ``cxlmemsim_server``
   * Handles memory allocation and deallocation
   * Tracks memory access patterns and statistics
   * Supports both shared memory and RDMA communication

Virtualization Components
--------------------------

**QEMU Integration**
   Modified QEMU provides virtual machines with CXL memory access.
   
   * Custom QEMU patches in ``qemu_integration/`` directory
   * Exposes CXL memory as ``/dev/dax0.0`` device inside VMs
   * Enables multi-VM testing on single physical hosts

**Network Infrastructure**
   Virtual networking connects multiple VM instances.
   
   * Bridge and TAP interfaces for VM communication
   * Scripts in ``script/`` directory for setup
   * Supports both single-host and multi-host configurations

Application Integration
-----------------------

**MPI Shim Library**
   Transparent integration with MPI-based applications.
   
   * Library: ``libmpi_cxl_shim.so``
   * Intercepts memory allocations via ``LD_PRELOAD``
   * Redirects allocations to CXL memory without code changes
   * Enables existing applications to use CXL memory

**Workload Support**
   Pre-configured workloads demonstrate CXL capabilities.
   
   * Located in ``workloads/`` directory
   * Includes GROMACS, TIGON, OSU benchmarks
   * Build scripts and configuration included

Repository Structure
====================

The OCEAN repository is organized to separate concerns:

Core Emulation
--------------

.. code-block:: text

   src/
   ├── cxl*.cpp           # CXL protocol implementation
   ├── policy.cpp         # Memory allocation policies
   ├── helper.cpp         # Utility functions
   ├── incore.cpp         # Core processing simulation
   ├── uncore.cpp         # Uncore components
   ├── perf.cpp           # Performance monitoring
   ├── main_server.cc     # Server entry point
   └── *communication.cpp # IPC and RDMA communication

Headers and Interfaces
----------------------

.. code-block:: text

   include/               # Public API headers

QEMU and Virtualization
-----------------------

.. code-block:: text

   qemu_integration/
   ├── src/               # QEMU-specific code
   ├── launch_qemu_*.sh   # VM launch scripts
   ├── start_server.sh    # Server startup script
   └── topology_*.txt     # Fabric topology files

Workloads and Applications
---------------------------

.. code-block:: text

   workloads/
   ├── gromacs/           # Molecular dynamics
   ├── tigon/             # Distributed database
   └── */                 # Other workloads

Testing and Validation
----------------------

.. code-block:: text

   microbench/            # Performance microbenchmarks
   use_cases/             # Example use cases
   artifact/              # Research artifacts

Support Infrastructure
----------------------

.. code-block:: text

   script/                # Setup and configuration scripts
   lib/                   # External libraries (bpftime, etc.)
   fpga/                  # FPGA-related components

How OCEAN Works
===============

Execution Flow
--------------

A typical OCEAN session progresses through these stages:

**1. System Initialization**

   The host system is prepared with required dependencies and network configuration.
   Scripts in ``script/`` automate this process.

**2. Server Startup**

   The CXL fabric server (``cxlmemsim_server``) starts and initializes the memory fabric.
   It creates shared memory regions and listens for VM connections.

**3. VM Launch**

   QEMU virtual machines launch with CXL device emulation enabled. Each VM connects
   to the fabric server and receives a CXL memory device (``/dev/dax0.0``).

**4. Application Execution**

   Applications run inside VMs, using the MPI shim library to transparently access
   CXL memory. Memory operations are routed through the emulated CXL fabric.

**5. Data Collection**

   Performance metrics, memory access patterns, and coherence statistics are collected
   throughout execution for analysis.

Memory Access Path
------------------

When an application accesses CXL memory:

1. **Application Request** - Application allocates or accesses memory
2. **Shim Interception** - MPI shim library intercepts the call
3. **Device I/O** - Request is routed to ``/dev/dax0.0``
4. **QEMU Handling** - QEMU forwards to CXL fabric server
5. **Server Processing** - Server performs the memory operation
6. **Statistics** - Access is logged for performance analysis
7. **Response** - Data is returned through the chain

This path enables:

* Transparent CXL memory access for applications
* Detailed performance instrumentation
* Multi-host memory sharing simulation
* Cache coherence protocol validation

Key Concepts
============

Memory Devices
--------------

CXL memory devices in OCEAN are emulated as:

* DAX (Direct Access) devices in guest VMs
* Backed by shared memory regions on the host
* Managed by the CXL fabric server
* Accessible through standard file system operations

Fabric Management
-----------------

The fabric manager coordinates:

* Memory allocation across devices
* Multi-host memory sharing
* Access tracking and statistics
* Topology management (switches, expanders)

Cache Coherence
---------------

OCEAN implements cache coherence protocols to ensure:

* Memory consistency across hosts
* Proper invalidation and update mechanisms
* Performance impact measurement

Memory Pooling
--------------

CXL memory pooling enables:

* Dynamic memory allocation from shared pools
* Resource sharing across multiple hosts
* Flexible capacity management
* Efficient utilization of memory resources

Design Principles
=================

OCEAN's architecture is guided by several principles:

**Transparency**
   Applications use CXL memory without modification through the shim library approach.

**Modularity**
   Components are loosely coupled with well-defined interfaces, enabling independent
   development and testing.

**Flexibility**
   Multiple server modes and build options support different research needs and
   deployment scenarios.

**Observability**
   Comprehensive instrumentation at multiple levels enables detailed performance analysis.

**Scalability**
   Architecture supports scaling from single-host development to multi-host distributed
   configurations.

Component Communication
=======================

The major components communicate through several mechanisms:

Server-VM Communication
-----------------------

* **Socket-based**: TCP/IP for control messages
* **Shared Memory**: High-performance data path (single host)
* **RDMA**: Low-latency communication (distributed hosts)

VM-Application Communication
-----------------------------

* **DAX Device**: Applications access ``/dev/dax0.0``
* **Shim Library**: LD_PRELOAD interception of memory calls
* **Standard I/O**: File operations on the DAX device

Instrumentation Data Flow
--------------------------

* **Hardware Counters**: Captured via perf subsystem
* **Software Tracing**: eBPF-based instrumentation
* **Server Logs**: Fabric operations and statistics
* **Application Metrics**: Workload-specific measurements

Next Steps
==========

For more information about specific aspects of OCEAN:

* **Building OCEAN** - See :doc:`getting-started`
* **Running Experiments** - Configure workloads and collect data
* **Configuration Options** - See :doc:`configuration` for build and runtime settings
