=======================
Configuration & Setup
=======================

This page covers OCEAN's configuration options for different deployment scenarios.
For initial installation and setup, see :doc:`getting-started`.

Build Configuration
===================

OCEAN uses CMake for build configuration with several options to customize compilation.

Build Options
-------------

SERVER_MODE
~~~~~~~~~~~

Controls whether to build for standalone server deployment.

**Default:** ``OFF``

.. code-block:: bash

   # Enable server mode
   cmake -DSERVER_MODE=ON ..
   
   # Disable server mode (default)
   cmake -DSERVER_MODE=OFF ..

**Effects:**

* When ``ON``: Builds ``cxlmemsim_latency`` utility, excludes QEMU integration and workloads
* When ``OFF`` (default): Includes ``qemu_integration/`` and ``workloads/`` subdirectories

**Use When:** Deploying standalone server without development tools.

ENABLE_RDMA
~~~~~~~~~~~

Controls RDMA support compilation.

**Default:** ``ON``

.. code-block:: bash

   # Enable RDMA (default)
   cmake -DENABLE_RDMA=ON ..
   
   # Disable RDMA
   cmake -DENABLE_RDMA=OFF ..

**Effects:**

* When ``ON``: Searches for RDMA libraries, builds ``cxlmemsim_server_rdma``
* When ``OFF``: Skips RDMA detection and RDMA server build

**Use When:** System has RDMA hardware or needs high-performance inter-host communication.

CMAKE_BUILD_TYPE
~~~~~~~~~~~~~~~~

Controls optimization level and debug information.

.. code-block:: bash

   # Release build (optimized, default for production)
   cmake -DCMAKE_BUILD_TYPE=Release ..
   
   # Debug build (debug symbols, no optimization)
   cmake -DCMAKE_BUILD_TYPE=Debug ..
   
   # Release with debug info
   cmake -DCMAKE_BUILD_TYPE=RelWithDebInfo ..

Build Configuration Matrix
---------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 15 30 20

   * - Configuration
     - SERVER_MODE
     - ENABLE_RDMA
     - Targets Built
     - Use Case
   * - **Default**
     - OFF
     - ON
     - All components
     - Full development
   * - **Server Deploy**
     - ON
     - ON
     - Server + utilities
     - Production deployment
   * - **No RDMA**
     - OFF
     - OFF
     - Core + main server
     - Systems without RDMA
   * - **Minimal**
     - ON
     - OFF
     - Core + main server
     - Minimal deployment

Quick Build Examples
--------------------

**Development Build:**

.. code-block:: bash

   cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
   cmake --build build -j$(nproc)

**Production Server:**

.. code-block:: bash

   cmake -S . -B build -DSERVER_MODE=ON -DCMAKE_BUILD_TYPE=Release
   cmake --build build -j$(nproc)

**Without RDMA:**

.. code-block:: bash

   cmake -S . -B build -DENABLE_RDMA=OFF
   cmake --build build -j$(nproc)

Compiler & Dependencies
=======================

Requirements
------------

**Compiler:**

* C++17 standard support required
* Minimum GCC 9.0 or Clang 9.0

**Required Libraries:**

* CMake 3.25.0+
* QEMU with KVM support
* libnuma

**Optional Libraries:**

* ``libibverbs`` and ``librdmacm`` - For RDMA support (``ENABLE_RDMA=ON``)
* ``spdlog`` - Enhanced logging (recommended)
* ``cxxopts`` - Command-line parsing (recommended)

.. note::
   
   For detailed installation instructions, see :doc:`getting-started`.

Compiler Flags
--------------

The build system automatically applies these flags:

* ``-Wall`` - All standard warnings
* ``-fPIC`` - Position-independent code
* ``-pthread`` - POSIX threads support
* ``-latomic`` - Atomic operations

Runtime Configuration
=====================

Server Configuration
--------------------

Command-Line Parameters
~~~~~~~~~~~~~~~~~~~~~~~

The CXL fabric server requires two parameters:

.. code-block:: bash

   ./cxlmemsim_server <port> <topology_file>

**Parameters:**

* ``<port>`` - TCP port for VM connections (e.g., 9999)
* ``<topology_file>`` - Path to CXL fabric topology file

**Example:**

.. code-block:: bash

   ./start_server.sh 9999 topology_simple.txt

Server Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**SPDLOG_LEVEL**
   Controls logging verbosity.
   
   **Values:** ``trace``, ``debug``, ``info``, ``warn``, ``error``, ``critical``
   
   **Default:** ``info``
   
   .. code-block:: bash
   
      export SPDLOG_LEVEL=debug
      ./cxlmemsim_server 9999 topology_simple.txt

Application Configuration
--------------------------

MPI Shim Environment Variables
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These variables configure the MPI shim library behavior:

**CXL_DAX_PATH**
   Path to CXL DAX device inside VM.
   
   **Default:** ``/dev/dax0.0``
   
   .. code-block:: bash
   
      export CXL_DAX_PATH="/dev/dax0.0"

**CXL_DAX_RESET**
   Reset allocation counter on first process.
   
   **Values:** ``0`` (disabled), ``1`` (enabled)
   
   .. code-block:: bash
   
      export CXL_DAX_RESET=1

**CXL_SHIM_TRACE**
   Enable detailed tracing output.
   
   **Values:** ``0`` (disabled), ``1`` (enabled)
   
   .. code-block:: bash
   
      export CXL_SHIM_TRACE=1

**CXL_SHIM_VERBOSE**
   Enable verbose output.
   
   **Values:** ``0`` (disabled), ``1`` (enabled)
   
   .. code-block:: bash
   
      export CXL_SHIM_VERBOSE=1

Passing Variables to MPI
~~~~~~~~~~~~~~~~~~~~~~~~~

Use the ``-x`` flag to pass environment variables:

.. code-block:: bash

   mpirun --allow-run-as-root \
          -x CXL_SHIM_TRACE=1 \
          -x CXL_DAX_PATH=/dev/dax0.0 \
          -x CXL_DAX_RESET=1 \
          -x LD_PRELOAD=$PWD/libmpi_cxl_shim.so \
          --hostfile ./hostfile \
          ./application

Topology Configuration
======================

CXL fabric topology is defined through configuration files specifying switches,
expanders, and their interconnections.

Topology File Format
--------------------

Topology files use a simple text format with two directives:

**Switch Declaration:**

.. code-block:: text

   switch <switch_id>

**Expander Declaration:**

.. code-block:: text

   expander <expander_id> <parent_switch>

Where:

* ``<switch_id>`` - Unique switch identifier (integer)
* ``<expander_id>`` - Unique expander identifier (integer)
* ``<parent_switch>`` - Parent switch name (e.g., ``switch1``)

Example: Simple Topology
-------------------------

File: ``topology_simple.txt``

.. code-block:: text

   switch 1
   switch 2
   expander 1 switch1
   expander 2 switch2
   expander 3 switch2

This creates:

* Two CXL switches (switch 1, switch 2)
* Three expanders:
  
  * Expander 1 → connected to switch 1
  * Expander 2 → connected to switch 2
  * Expander 3 → connected to switch 2

Example: Hierarchical Topology
-------------------------------

File: ``topology_hierarchical.txt``

.. code-block:: text

   switch 1
   switch 2
   switch 3
   expander 1 switch1
   expander 2 switch1
   expander 3 switch2
   expander 4 switch2
   expander 5 switch3
   expander 6 switch3

This creates a more complex hierarchy with three switches and six expanders,
two expanders per switch.

Topology Design Guidelines
---------------------------

**For Development:**
   Start with simple topologies (1-2 switches, 2-4 expanders) to understand behavior.

**For Testing:**
   Use topologies that match your research scenario's switch/expander configuration.

**For Scaling:**
   Test progressively complex topologies to study scalability characteristics.

Configuration Best Practices
=============================

Development Configuration
--------------------------

Recommended settings for development:

.. code-block:: bash

   cmake -S . -B build \
         -DCMAKE_BUILD_TYPE=Debug \
         -DSERVER_MODE=OFF \
         -DENABLE_RDMA=ON

**Why:**

* Debug symbols help with troubleshooting
* QEMU integration and workloads included
* RDMA available if hardware present

Testing Configuration
---------------------

Recommended settings for performance testing:

.. code-block:: bash

   cmake -S . -B build \
         -DCMAKE_BUILD_TYPE=Release \
         -DSERVER_MODE=OFF \
         -DENABLE_RDMA=ON

**Why:**

* Optimized binaries for accurate performance measurement
* All workloads available for testing
* RDMA for high-performance scenarios

Production Configuration
------------------------

Recommended settings for production deployment:

.. code-block:: bash

   cmake -S . -B build \
         -DCMAKE_BUILD_TYPE=Release \
         -DSERVER_MODE=ON \
         -DENABLE_RDMA=ON

**Why:**

* Minimal dependencies (no QEMU/workload build tools)
* Optimized for performance
* Lightweight server deployment

.. note::
   
   Set ``SPDLOG_LEVEL=warn`` or ``error`` in production to reduce logging overhead.

Configuration Troubleshooting
==============================

Build Issues
------------

**CMake version too old**

.. code-block:: bash

   # Upgrade CMake
   pip install --user --upgrade cmake

**RDMA libraries not found**

.. code-block:: bash

   # Option 1: Install RDMA libraries (see Getting Started)
   # Option 2: Disable RDMA
   cmake -DENABLE_RDMA=OFF ..

**Compiler not found or too old**

Ensure GCC 9.0+ or Clang 9.0+ is installed and in PATH.

Runtime Issues
--------------

**Server fails to start**

* Check port not in use: ``netstat -tuln | grep 9999``
* Verify topology file exists and is readable
* Check ``/dev/shm`` permissions

**Application cannot access CXL memory**

* Verify ``/dev/dax0.0`` exists in VM
* Confirm ``LD_PRELOAD`` points to shim library
* Check environment variables are set correctly

**Insufficient logging output**

.. code-block:: bash

   # Increase logging level
   export SPDLOG_LEVEL=debug

Configuration Reference Summary
===============================

Build Options Quick Reference
------------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 60

   * - Option
     - Default
     - Purpose
   * - ``SERVER_MODE``
     - OFF
     - Standalone server deployment
   * - ``ENABLE_RDMA``
     - ON
     - RDMA support
   * - ``CMAKE_BUILD_TYPE``
     - None
     - Optimization level

Environment Variables Quick Reference
--------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Purpose
   * - ``SPDLOG_LEVEL``
     - Server logging level
   * - ``CXL_DAX_PATH``
     - CXL device path in VM
   * - ``CXL_DAX_RESET``
     - Reset allocation counter
   * - ``CXL_SHIM_TRACE``
     - Enable shim tracing
   * - ``CXL_SHIM_VERBOSE``
     - Enable verbose output

Next Steps
==========

After configuring OCEAN:

* **Run experiments** - Execute workloads and collect data
* **Analyze results** - Review performance metrics
* **Tune settings** - Adjust based on experimental results

For more information:

* :doc:`getting-started` - Installation and initial setup
* :doc:`architecture` - Understanding OCEAN's components
* GitHub repository - Latest configuration options and examples