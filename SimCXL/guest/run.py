#!/usr/bin/env python3
"""Launch one explicitly requested guest workload with the CXL metrics collector."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BASIC = {'memory_pilot', 'stream', 'pointer_chase'}
ALL = BASIC | {'ann', 'bert', 'dlrm', 'kmeans', 'llama_cpp'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--workload', choices=sorted(ALL), default='memory_pilot')
    parser.add_argument('--size', choices=['full', 'smoke'], default='full')
    parser.add_argument('--trial-minutes', type=float, help='Sample at most this many minutes of simulation; retain partial stats')
    parser.add_argument('--cores', type=int, default=1)
    parser.add_argument('--node', type=int, default=1, help='1=CXL; 0=DRAM baseline')
    parser.add_argument('--boot-cpu', choices=['auto', 'atomic', 'kvm'], default='auto')
    parser.add_argument('--cpu', choices=['timing', 'o3'], default='timing')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--window-ticks', type=int, default=1_000_000_000)
    parser.add_argument('--random-seed', type=int, default=5489)
    parser.add_argument('--cxl-version', default='unspecified')
    parser.add_argument('--cxl-size', default='8GB')
    parser.add_argument('--l2-size', default='2MB')
    parser.add_argument('--l3-size', default='96MB')
    parser.add_argument('--l3-assoc', type=int, default=48)
    parser.add_argument('--no-cxl-trace', action='store_true',
                        help='Diagnostic only: run the same simulator without CXL tracing/reporting')
    parser.add_argument('--read-bandwidth', type=float, default=0, help='Configured payload bytes/s, 0=unknown')
    parser.add_argument('--write-bandwidth', type=float, default=0)
    parser.add_argument('--max-ticks', type=int)
    parser.add_argument('--print-command', action='store_true')
    args = parser.parse_args()
    if args.cores < 1 or args.node not in (0, 1) or args.window_ticks < 1:
        parser.error('cores/window must be positive; node must be 0 or 1')
    if args.l3_assoc < 1:
        parser.error('--l3-assoc must be positive')
    if any(not math.isfinite(x) or x < 0 for x in (args.read_bandwidth, args.write_bandwidth)):
        parser.error('Bandwidth must be finite and nonnegative')
    if args.trial_minutes is not None and (not math.isfinite(args.trial_minutes) or args.trial_minutes <= 0):
        parser.error('--trial-minutes must be finite and positive')
    image = HERE / 'images/btp.img'
    kernel = HERE / 'images/vmlinux'
    receipt = HERE / 'images/btp.img.json'
    binary = REPO / 'build/X86/gem5.opt'
    for file in (image, kernel, receipt, binary):
        if not file.is_file():
            parser.error(f'Missing {file}; complete guest preparation and build gem5 first')
    prepared = json.loads(receipt.read_text())
    if args.workload not in BASIC and prepared['profile'] != 'all':
        parser.error('This workload requires an image prepared with --profile all')
    kvm = os.access('/dev/kvm', os.R_OK | os.W_OK)
    if args.boot_cpu == 'kvm' and not kvm:
        parser.error('KVM requested but /dev/kvm is not accessible')
    boot = ('kvm' if kvm else 'atomic') if args.boot_cpu == 'auto' else args.boot_cpu
    output = (args.output_dir or HERE / 'results' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + args.size + '-' + args.workload)).resolve()
    command = [sys.executable, str(REPO / 'util/cxl_metrics.py'), 'run',
        '--output-dir', str(output), '--workload', args.workload,
        '--placement-policy', f'numactl-membind-{args.node}', '--cxl-version', args.cxl_version,
        '--window-ticks', str(args.window_ticks), '--random-seed', str(args.random_seed),
        '--workload-size', args.size,
        *(['--trial-seconds', str(args.trial_minutes * 60)] if args.trial_minutes is not None else []),
        *(['--no-cxl-trace'] if args.no_cxl_trace else []), '--',
        str(binary), str(HERE / 'simulate.py'), '--kernel', str(kernel), '--disk', str(image),
        '--root-device', prepared['root_device'], '--workload', args.workload, '--size', args.size,
        '--node', str(args.node), '--cores', str(args.cores), '--boot-cpu', boot,
        '--cpu', args.cpu, '--cxl-size', args.cxl_size,
        '--l2-size', args.l2_size, '--l3-size', args.l3_size, '--l3-assoc', str(args.l3_assoc),
        '--read-bandwidth', str(args.read_bandwidth), '--write-bandwidth', str(args.write_bandwidth)]
    if args.max_ticks is not None:
        if args.max_ticks < 1:
            parser.error('--max-ticks must be positive')
        command += ['--max-ticks', str(args.max_ticks)]
    print(__import__('shlex').join(command), flush=True)
    if args.print_command:
        return
    output.mkdir(parents=True, exist_ok=False)
    (output / 'guest-image-provenance.json').write_text(receipt.read_text())
    from smoke import SETTINGS
    (output / 'workload-config.json').write_text(json.dumps({'workload': args.workload,
        'size': args.size, 'parameters': SETTINGS[args.workload] if args.size == 'smoke' else 'full defaults',
        'trial_minutes': args.trial_minutes, 'cxl_trace_enabled': not args.no_cxl_trace,
        'cpu_switch_boundary': 'inference-roi' if args.workload == 'dlrm' else 'workload-process-start',
        'cache': {'l2_size': args.l2_size, 'l3_size': args.l3_size, 'l3_assoc': args.l3_assoc}}, indent=2) + '\n')
    result = subprocess.run(command, cwd=REPO)
    if result.returncode:
        raise SystemExit(result.returncode)
    if args.no_cxl_trace:
        if not json.loads((output / 'guest-run-status.json').read_text())['completed']:
            raise SystemExit('Diagnostic guest execution did not complete')
        print('Completed diagnostic without CXL tracing; no CXL report: ' + str(output))
        return
    report = json.loads((output / 'cxl-metrics.json').read_text())
    phases = [p for p in report['phases'] if p['metadata']['phase'] == 'workload']
    if len(phases) != 1 or not phases[0]['metadata']['complete']:
        raise SystemExit('Missing complete workload phase: check collector build and phase markers')
    if args.node == 1 and phases[0]['metrics']['cxl.total_requests'] == 0:
        raise SystemExit('No CXL requests in workload phase; do not use this run as a CXL measurement')
    print('Completed guest workload and CXL report: ' + str(output))


if __name__ == '__main__':
    main()
