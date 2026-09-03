"""Disk-free timing smoke: mixed CXL traffic through a shared switch, two endpoints."""
import m5
from m5.objects import (AddrRange, CXLBridge, CXLMemCtrl, IOXBar, Pc,
                        PyTrafficGen, Root, SimpleMemory, SrcClockDomain,
                        System, VoltageDomain)

system = System(mem_mode="timing")
system.clk_domain = SrcClockDomain(clock="1GHz", voltage_domain=VoltageDomain())
system.pc = Pc()
system.io = IOXBar(width=8)
system.pc.attachIO(system.io)
ranges = [AddrRange(0x100000000 + i * 65536, size=65536) for i in range(2)]
system.mem_ranges = ranges
system.bridge = CXLBridge(ranges=ranges, bridge_lat="2ns", proto_proc_lat="1ns",
                          req_fifo_depth=4, resp_fifo_depth=4,
                          metrics_read_bandwidth=8e9, metrics_write_bandwidth=8e9,
                          metrics_link_width=8, metrics_link_speed=16)
system.bridge.mem_side_port = system.io.cpu_side_ports
system.system_port = system.io.cpu_side_ports
system.endpoints = [CXLMemCtrl(host=system.pc.pci_host, pci_dev=6+i, pci_bus=0, pci_func=0,
                    cxl_mem_range=r, proto_proc_lat="2ns", req_size=2, rsp_size=2,
                    metrics_read_bandwidth=2e9, metrics_write_bandwidth=2e9,
                    metrics_link_width=8, metrics_link_speed=16)
                    for i, r in enumerate(ranges)]
system.memories = [SimpleMemory(range=r, latency="30ns", bandwidth="2GB/s") for r in ranges]
for endpoint, memory in zip(system.endpoints, system.memories):
    endpoint.pio = system.io.mem_side_ports
    endpoint.cxl_rsp_port = system.io.mem_side_ports
    endpoint.mem_req_port = memory.port
system.generator = PyTrafficGen()
system.generator.port = system.bridge.cpu_side_port
root = Root(full_system=False, system=system)
m5.instantiate()

def traffic():
    yield system.generator.createLinear(2000000, 0x100000000, 0x100020000,
                                        64, 50, 1000, 1000, 0)
    yield system.generator.createIdle(1000000)
    yield system.generator.createExit(0)

system.generator.start(traffic())
exit_event = m5.simulate()
print("CXL smoke completed:", exit_event.getCause())
