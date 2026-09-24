"""Full-system SimCXL guest: boot, switch to timing, run one selected workload."""
import argparse
import json
from pathlib import Path
import shlex
import time

import m5
from gem5.components.boards.x86_board import X86Board
from gem5.components.cachehierarchies.classic.private_l1_private_l2_shared_l3_cache_hierarchy import PrivateL1PrivateL2SharedL3CacheHierarchy
from gem5.components.memory.single_channel import DIMM_DDR5_4400
from gem5.components.processors.cpu_types import CPUTypes
from gem5.components.processors.simple_switchable_processor import SimpleSwitchableProcessor
from gem5.isas import ISA
from gem5.resources.resource import DiskImageResource, KernelResource
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.simulator import Simulator

parser = argparse.ArgumentParser()
parser.add_argument('--kernel', type=Path, required=True)
parser.add_argument('--disk', type=Path, required=True)
parser.add_argument('--root-device', required=True)
parser.add_argument('--workload', required=True)
parser.add_argument('--size', choices=['full', 'smoke'], default='full')
parser.add_argument('--node', type=int, default=1)
parser.add_argument('--cores', type=int, default=1)
parser.add_argument('--boot-cpu', choices=['atomic', 'kvm'], default='atomic')
parser.add_argument('--cpu', choices=['timing', 'o3'], default='timing')
parser.add_argument('--cxl-size', default='8GB')
parser.add_argument('--l2-size', default='2MB')
parser.add_argument('--l3-size', default='96MB')
parser.add_argument('--l3-assoc', type=int, default=48)
parser.add_argument('--read-bandwidth', type=float, default=0)
parser.add_argument('--write-bandwidth', type=float, default=0)
parser.add_argument('--max-ticks', type=int, default=m5.MaxTick)
args = parser.parse_args()
processor = SimpleSwitchableProcessor(
    starting_core_type=CPUTypes.KVM if args.boot_cpu == 'kvm' else CPUTypes.ATOMIC,
    switch_core_type=CPUTypes.O3 if args.cpu == 'o3' else CPUTypes.TIMING,
    isa=ISA.X86, num_cores=args.cores)
if args.boot_cpu == 'kvm':
    for core in processor.start:
        core.core.usePerf = False
board = X86Board(
    clk_freq='2.4GHz', processor=processor,
    memory=DIMM_DDR5_4400(size='3GB'),
    cxl_memory=DIMM_DDR5_4400(size=args.cxl_size),
    cache_hierarchy=PrivateL1PrivateL2SharedL3CacheHierarchy(
        l1d_size='48kB', l1d_assoc=6, l1i_size='32kB', l1i_assoc=8,
        l2_size=args.l2_size, l2_assoc=16,
        l3_size=args.l3_size, l3_assoc=args.l3_assoc), is_asic=True)
endpoint = board.pc.south_bridge.cxl_device
endpoint.metrics_read_bandwidth = args.read_bandwidth
endpoint.metrics_write_bandwidth = args.write_bandwidth
board.bridge.metrics_read_bandwidth = args.read_bandwidth
board.bridge.metrics_write_bandwidth = args.write_bandwidth
# The m5 utility uses address-triggered operations during KVM boot. Named
# phase markers execute only after the first exit switches to timing mode.
from smoke import boot_setup, runtime_setup
setup_commands = runtime_setup()
runner = ['/opt/btp/run-workload.sh', args.workload, str(args.node), str(args.cores)]
if args.size == 'smoke':
    setup_commands = boot_setup(args.workload)
    runner = ['bash', '/opt/btp/smoke/run-workload.sh', args.workload, str(args.node), str(args.cores), 'smoke']
switch_at_application_roi = args.workload == 'dlrm'
command = '\n'.join([
    '#!/bin/bash', 'set -euo pipefail', *setup_commands,
    *([] if switch_at_application_roi else ['/opt/btp/bin/m5 --addr exit']),
    'set +e',
    shlex.join(runner),
    'rc=$?', 'set -e',
    'if [ "$rc" -ne 0 ]; then /opt/btp/bin/m5 --addr fail "$rc"; fi',
    '/opt/btp/bin/m5 --addr exit',
])
board.set_kernel_disk_workload(
    kernel=KernelResource(local_path=str(args.kernel)),
    disk_image=DiskImageResource(local_path=str(args.disk)),
    readfile_contents=command,
    kernel_args=['console=ttyS0', 'earlyprintk=ttyS0', 'lpj=7999923',
                 'root=' + args.root_device, 'rw', 'init=/opt/btp/boot.sh', 'idle=nomwait'])
exits = {'count': 0}
progress_path = Path(m5.options.outdir) / 'progress.json'
progress = {
    'workload': args.workload,
    'stage': 'kvm_initialization' if switch_at_application_roi else 'boot',
    'started_unix': time.time(),
    'updated_unix': time.time(),
    'switch_tick': None,
    'completion_tick': None,
}

def write_progress(stage, **updates):
    progress.update(stage=stage, updated_unix=time.time(), **updates)
    progress_path.write_text(json.dumps(progress, indent=2) + '\n')

write_progress(progress['stage'])

def on_exit():
    exits['count'] += 1
    if exits['count'] == 1:
        print('Switching from boot CPU to detailed CPU at ' +
              ('DLRM inference ROI' if switch_at_application_roi else 'workload start'),
              flush=True)
        processor.switch()
        m5.stats.reset()
        write_progress('detailed_roi', switch_tick=simulator.get_current_tick())
        return False
    write_progress('roi_complete', completion_tick=simulator.get_current_tick())
    return True

simulator = Simulator(board=board, on_exit_event={ExitEvent.EXIT: on_exit})
simulator.run(max_ticks=args.max_ticks)
cause = simulator.get_last_exit_event_cause()
status = Path(m5.options.outdir) / 'workload-status.txt'
roi_status = Path(m5.options.outdir) / 'roi-status.txt'
if switch_at_application_roi:
    passed = (exits['count'] == 2 and roi_status.exists() and
              'roi_completed=1\n' in roi_status.read_text())
else:
    passed = exits['count'] == 2 and status.exists() and 'exit_code=0\n' in status.read_text()
write_progress('complete' if passed else 'failed',
               completion_tick=simulator.get_current_tick())
(Path(m5.options.outdir) / 'guest-run-status.json').write_text(json.dumps({
    'completed': passed, 'exit_cause': cause, 'normal_exit_count': exits['count'],
    'tick': simulator.get_current_tick()}, indent=2) + '\n')
if not passed:
    print('Guest workload did not complete successfully; inspect the serial console and guest-run-status.json')
    raise SystemExit(1)
