#!/usr/bin/env python3
"""Run matched smoke inputs with CXL tracing off/on; never build implicitly."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def final_stats(path):
    current, last = {}, {}
    for line in path.read_text().splitlines():
        if 'Begin Simulation Statistics' in line:
            current = {}
        elif 'End Simulation Statistics' in line:
            last = current
        else:
            parts = line.split()
            if len(parts) > 1 and parts[0] in ('simSeconds', 'hostSeconds', 'simInsts', 'hostInstRate'):
                current[parts[0]] = float(parts[1])
    return last


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--workload', choices=['memory_pilot', 'stream', 'ann'], default='stream')
    parser.add_argument('--l2-size', default='2MB')
    parser.add_argument('--l3-size', default='96MB')
    parser.add_argument('--l3-assoc', type=int, default=48)
    parser.add_argument('--order', choices=['off-on', 'on-off'], default='off-on')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error('Choose a new output directory')
    commands = []
    for mode in args.order.split('-'):
        command = [sys.executable, str(HERE / 'run.py'), '--workload', args.workload,
            '--size', 'smoke', '--cores', '1', '--node', '1', '--boot-cpu', 'kvm', '--random-seed', '5489',
            '--l2-size', args.l2_size, '--l3-size', args.l3_size, '--l3-assoc', str(args.l3_assoc),
            '--output-dir', str(output / ('trace-' + mode))]
        if mode == 'off':
            command.append('--no-cxl-trace')
        commands.append((mode, command))
        print(shlex.join(command), flush=True)
    if args.dry_run:
        return 0
    output.mkdir(parents=True)
    result = {'workload': args.workload, 'size': 'smoke', 'order': args.order,
              'note': 'Trace-off is diagnostic only. KVM startup and host load can vary; one pair is an initial estimate, not a controlled confidence interval.', 'runs': {}}
    for mode, command in commands:
        print('Running trace-' + mode, flush=True)
        with (output / ('trace-' + mode + '.log')).open('w') as log:
            rc = subprocess.run(command, cwd=HERE.parent, stdout=log, stderr=subprocess.STDOUT).returncode
        entry = {'exit_code': rc}
        folder = output / ('trace-' + mode)
        for filename, key in [('timing.json', 'timing'), ('guest-run-status.json', 'guest')]:
            if (folder / filename).exists():
                entry[key] = json.loads((folder / filename).read_text())
        if (folder / 'stats.txt').exists():
            entry['stats'] = final_stats(folder / 'stats.txt')
        result['runs'][mode] = entry
        (output / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
        if rc:
            print('Diagnostic failed; inspect ' + str(output / ('trace-' + mode + '.log')))
            return 1
    on, off = (result['runs'][mode]['stats'] for mode in ('on', 'off'))
    result['trace_on_over_off_host_time_ratio'] = on['hostSeconds'] / off['hostSeconds']
    result['trace_on_over_off_host_time_per_instruction_ratio'] = (
        (on['hostSeconds'] / on['simInsts']) / (off['hostSeconds'] / off['simInsts']))
    result['instruction_count_change_fraction'] = on['simInsts'] / off['simInsts'] - 1
    result['simulated_time_change_fraction'] = on['simSeconds'] / off['simSeconds'] - 1
    (output / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    print('Comparison saved to ' + str(output / 'comparison.json'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
