===============
Getting Started
===============

This guide walks you through installing OCEAN, building the necessary components,
and running your first CXL emulation experiment.

Prerequisites
=============

System Requirements
-------------------

OCEAN requires a Linux-based system with:

* **Operating System**: Ubuntu 20.04 or later (or equivalent Linux distribution)
* **CPU**: x86_64 architecture with virtualization support (Intel VT-x or AMD-V)
* **Memory**: At least 16 GB RAM (32 GB recommended for multi-host setups)
* **Disk Space**: At least 50 GB free space
* **Kernel**: Linux kernel 5.0 or later with KVM support

Required Software
-----------------

The following tools must be installed:

* **CMake** 3.25.0 or higher
* **GCC/G++** 9.0 or higher (C++17 support required)
* **Git** for cloning the repository
* **Python** 3.8 or higher
* **QEMU** with KVM support
* **Make** and standard build tools

Installation
============

Step 1: Clone the Repository
-----------------------------

.. code-block:: bash

   git clone https://github.com/cxl-emu/OCEAN.git
   cd OCEAN

Step 2: Run Host Setup Script
------------------------------

The setup script installs required dependencies and configures the host system:

.. code-block:: bash

   bash ./script/setup_host.sh

This script will:

* Install build tools (CMake, GCC, Make)
* Install QEMU and KVM packages
* Install development libraries
* Configure kernel modules for device DAX
* Set up permissions for ``/dev/kvm``
* Configure shared memory settings

Step 3: Configure Network
--------------------------

For multi-host simulation, set up virtual network bridges.

**Single Machine Setup** (multiple VMs on one host):

.. code-block:: bash

   # Replace 2 with the number of hosts you want to simulate
   bash ./script/setup_network.sh 2

This creates virtual network bridges and TAP interfaces for VM communication.

**Multiple Physical Machines** (optional):

If using separate physical machines for hosts:

.. code-block:: bash

   # Run on each machine
   bash ./script/setup_optional_cross_machine_network.sh 2

Ensure machines can communicate over the network and configure firewall rules as needed.

Building OCEAN
==============

Build QEMU Integration
-----------------------

OCEAN includes modified QEMU components for CXL device emulation:

.. code-block:: bash

   cd qemu_integration
   mkdir build
   cd build
   cmake ..
   make -j$(nproc)
   sudo make install

This builds:

* ``cxlmemsim_server`` - CXL fabric manager
* ``cxlmemsim_server_rdma`` - RDMA-enabled server (if RDMA libraries available)
* Modified QEMU binaries with CXL support
* VM launch scripts

Build Core Components
----------------------

this builds core libraries:

.. code-block:: bash

   mkdir build
   cd build
   cmake ..
   make -j$(nproc)

**Build Options:**

For different configurations:

.. code-block:: bash

   # Server mode (standalone deployment)
   cmake -DSERVER_MODE=ON ..
   
   # Without RDMA support
   cmake -DENABLE_RDMA=OFF ..
   
   # Debug build
   cmake -DCMAKE_BUILD_TYPE=Debug ..

Verify the build by checking for these files:

.. code-block:: bash

   ls -l build/
   # Should show:
   # - libcxlmemsim.a
   # - cxlmemsim_server

Preparing Virtual Machine Images
=================================

Download Base Images
--------------------

OCEAN provides pre-configured VM images:

.. code-block:: bash

   cd qemu_integration/build
   wget https://asplos.dev/about/qemu.img
   wget https://asplos.dev/about/bzImage

These images include:

* Pre-configured Linux system with CXL utilities
* Kernel with CXL and DAX support
* Default credentials: username ``root``, password ``victor129``

Create Per-Host Images
-----------------------

For multi-host setups, create separate images for each VM:

.. code-block:: bash

   cp qemu.img qemu1.img
   cp qemu.img qemu2.img
   # Create as many copies as needed

Each image will be customized with unique hostnames and IP addresses.

Running Your First Experiment
==============================

Step 1: Start the CXL Fabric Server
------------------------------------

The server manages shared CXL memory across all hosts:

.. code-block:: bash

   cd qemu_integration/build
   ./start_server.sh 9999 topology_simple.txt

The server will:

* Initialize the CXL memory fabric
* Listen for VM connections on port 9999
* Manage memory allocation and coherence

Leave this terminal running.

Step 2: Launch Virtual Machines
--------------------------------

Open new terminals for each VM.

**Terminal 2 - Launch VM 0:**

.. code-block:: bash

   cd qemu_integration/build
   sudo ../launch_qemu_cxl.sh

**Terminal 3 - Launch VM 1:**

.. code-block:: bash

   cd qemu_integration/build
   sudo ../launch_qemu_cxl1.sh

Log in with username ``root`` and password ``victor129``.

Step 3: Configure VM Network Settings
--------------------------------------

**In VM 1** (first boot only):

.. code-block:: bash

   # Update network configuration
   vi /usr/local/bin/*.sh
   # Change 192.168.100.10 to 192.168.100.11
   
   # Update hostname
   vi /etc/hostname
   # Change node0 to node1
   
   # Reboot
   shutdown -r now

Repeat for additional VMs, incrementing IP addresses (192.168.100.12, .13, etc.)
and hostnames (node2, node3, etc.).

Step 4: Verify CXL Device
--------------------------

Inside each VM, verify the CXL device is accessible:

.. code-block:: bash

   ls -l /dev/dax0.0

Expected output:

.. code-block:: text

   crw------- 1 root root 241, 0 Dec 10 12:34 /dev/dax0.0

Check NUMA configuration:

.. code-block:: bash

   numactl --hardware

Step 5: Test Inter-VM Communication
------------------------------------

From VM 0, ping VM 1:

.. code-block:: bash

   ping 192.168.100.11

From VM 1, ping VM 0:

.. code-block:: bash

   ping 192.168.100.10



Next Steps
==========

Now that OCEAN is running, you can:

* **Explore Architecture** - See :doc:`architecture` to understand OCEAN's components
* **Run Workloads** - Configure and run applications like GROMACS, TIGON, or MPI benchmarks
* **Customize Configuration** - See :doc:`configuration` for advanced setup options

Troubleshooting
===============

Common Issues
-------------

**QEMU fails to start**

* Verify KVM is enabled: ``lsmod | grep kvm``
* Check permissions: ``ls -l /dev/kvm``
* Ensure sufficient memory: ``free -h``

**CXL device not found (/dev/dax0.0 missing)**

* Verify the CXL server is running
* Check QEMU launch script includes CXL device parameters
* Review dmesg for errors: ``dmesg | grep -i cxl``

**VMs cannot communicate**

* Verify network bridges: ``ip addr show br0``
* Check TAP interfaces: ``ip link show tap0 tap1``
* Test host connectivity: ``ping 192.168.100.10``

**Build errors**

* Ensure CMake version: ``cmake --version`` (need 3.25+)
* Check compiler: ``g++ --version`` (need 9.0+)
* Install missing dependencies from setup script

For more detailed troubleshooting, check the GitHub issues page.

Getting Help
============

If you encounter problems:

* Check the `GitHub Issues <https://github.com/cxl-emu/OCEAN/issues>`_
* Review the `CXL-EMU Website <https://cxl-emu.github.io>`_
