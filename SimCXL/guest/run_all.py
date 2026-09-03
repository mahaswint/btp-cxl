#!/usr/bin/env python3
"""Run guest workloads sequentially and record a suite manifest; never build implicitly."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

from run import ALL, BASIC

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ORDER = ('memory_pilot', 'stream', 'pointer_chase', 'ann', 'bert', 'kmeans', 'dlrm', 'llama_cpp')


def select_workloads(profile, suite, requested):
    if profile not in ('basic', 'all'):
        raise ValueError(f'Unknown guest image profile: {profile}')
    available = BASIC if profile == 'basic' else ALL
    selected = requested or [name for name in ORDER
                             if name in (available if suite == 'installed' else BASIC if suite == 'basic' else ALL)]
    if len(selected) != len(set(selected)):
        raise ValueError('Each workload should be selected only once; use --repeat for repeated measurements')
    missing = set(selected) - available
    if missing:
        raise ValueError('Image has profile basic; these workloads require profile all: ' + ', '.join(sorted(missing)))
    return selected


def save_summary(output, summary):
    temporary = output / 'summary.json.part'
    temporary.write_text(json.dumps(summary, indent=2) + '\n')
    temporary.replace(output / 'summary.json')
    with (output / 'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['workload', 'repeat', 'status', 'exit_code', 'wall_seconds',
                                                   'output_dir', 'runner_log', 'metrics_file'])
        writer.writeheader()
        writer.writerows(summary['runs'])
    if summary.get('trial_minutes'):
        measured = []
        for row in summary['runs']:
            timing = Path(row['output_dir']) / 'timing.json'
            entry = {'workload': row['workload'], 'status': row['status'],
                     'wall_seconds': row['wall_seconds']}
            if timing.exists():
                entry.update(json.loads(timing.read_text()))
            entry['within_45_minutes'] = (row['wall_seconds'] <= 2700
                                         if row['status'] == 'completed' else None)
            measured.append(entry)
        complete = all(r['status'] == 'completed' for r in summary['runs'])
        total = sum(r['wall_seconds'] or 0 for r in summary['runs'])
        (output / 'calibration.json').write_text(json.dumps({
            'size': summary['size'], 'measurements': measured,
            'completed_suite_wall_seconds': total if complete else None,
            'under_six_hours_measured': total < 21600 if complete else None,
            'note': 'Partial trials do not establish total runtime. Model initialization and reporting are fixed costs; do not extrapolate from instruction rate alone.',
        }, indent=2) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        'Pass additional guest/run.py options after --, e.g. -- --cpu o3 --max-ticks 1000000000000')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--suite', choices=['installed', 'basic', 'all'], default='installed')
    selection.add_argument('--workloads', nargs='+', choices=ORDER)
    parser.add_argument('--cores', type=int, default=1)
    parser.add_argument('--node', type=int, choices=[0, 1], default=1)
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--size', choices=['full', 'smoke'], default='full')
    parser.add_argument('--trial-minutes', type=float, help='Per-workload calibration sample; there is no suite time limit')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--keep-going', action='store_true', help='Continue after a failed workload')
    parser.add_argument('--dry-run', action='store_true', help='Validate prerequisites and print commands without running')
    parser.add_argument('run_options', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.cores < 1 or args.repeat < 1:
        parser.error('--cores and --repeat must be positive')
    forwarded = args.run_options
    if forwarded[:1] == ['--']:
        forwarded = forwarded[1:]
    for option in forwarded:
        if option.split('=', 1)[0] in ('--workload', '--output-dir', '--print-command', '--help', '-h', '--size', '--trial-minutes'):
            parser.error(f'{option} is managed by the suite runner')
    receipt = HERE / 'images/btp.img.json'
    try:
        profile = json.loads(receipt.read_text())['profile']
        selected = select_workloads(profile, args.suite, args.workloads)
    except (OSError, KeyError, ValueError) as exc:
        parser.error(f'Cannot select guest workloads: {exc}')
    unavailable = {name: 'requires guest profile all' for name in ORDER if profile == 'basic' and name not in BASIC}
    unavailable['gups'] = 'guest build/run configuration is not implemented'
    print('Selected workloads: ' + ', '.join(selected), flush=True)
    for name, reason in unavailable.items():
        print(f'Unavailable: {name}: {reason}', flush=True)
    output = (args.output_dir or HERE / 'results' / (
        'suite-' + args.size + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'))).resolve()
    if output.exists():
        parser.error(f'Results directory already exists: {output}; choose a new directory')
    summary = {'image_profile': profile, 'size': args.size, 'trial_minutes': args.trial_minutes,
               'unavailable': unavailable, 'runs': []}
    commands = []
    for repetition in range(1, args.repeat + 1):
        for name in selected:
            label = f'{len(commands) + 1:03d}-{name}-r{repetition}'
            run_output = output / label
            command = [sys.executable, str(HERE / 'run.py'), '--workload', name,
                       '--cores', str(args.cores), '--node', str(args.node),
                       '--output-dir', str(run_output), '--size', args.size,
                       *(['--trial-minutes', str(args.trial_minutes)] if args.trial_minutes is not None else []), *forwarded]
            commands.append(command)
            summary['runs'].append({'workload': name, 'repeat': repetition, 'status': 'not_run',
                'exit_code': None, 'wall_seconds': None, 'output_dir': str(run_output), 'runner_log': str(output / (label + '.log')),
                'metrics_file': str(run_output / 'cxl-metrics.json')})
    # Reuse single-workload validation, including image, binary, options and KVM.
    # Validate each distinct workload before starting any simulations.
    for command in commands[:len(selected)]:
        check = subprocess.run([*command, '--print-command'], cwd=REPO, text=True, capture_output=True)
        if check.returncode:
            parser.error(check.stderr.strip() or check.stdout.strip() or 'Workload preflight failed')
    if args.dry_run:
        for command in commands:
            print(shlex.join(command))
        return 0
    output.mkdir(parents=True, exist_ok=False)
    (output / 'guest-image-provenance.json').write_text(receipt.read_text())
    save_summary(output, summary)
    exit_code = 0
    for index, (record, command) in enumerate(zip(summary['runs'], commands), 1):
        print(f'[{index}/{len(commands)}] Running {record["workload"]}; log: {record["runner_log"]}', flush=True)
        record['status'] = 'running'
        save_summary(output, summary)
        started = time.monotonic()
        try:
            with Path(record['runner_log']).open('w') as log:
                log.write(shlex.join(command) + '\n')
                log.flush()
                result = subprocess.run(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
            record['exit_code'] = result.returncode
            record['status'] = ('completed' if result.returncode == 0 else
                                'trial_incomplete' if result.returncode == 124 and args.trial_minutes else 'failed')
        except KeyboardInterrupt:
            record.update(status='interrupted', exit_code=130)
        except OSError as exc:
            print(f'Launch failed: {exc}', file=sys.stderr)
            record.update(status='failed', exit_code=1)
        record['wall_seconds'] = time.monotonic() - started
        if record['status'] == 'trial_incomplete':
            record['metrics_file'] = str(Path(record['output_dir']) / 'cxl-metrics.partial.json')
        save_summary(output, summary)
        print(f'{record["workload"]}: {record["status"]}', flush=True)
        if record['exit_code']:
            exit_code = 130 if record['status'] == 'interrupted' else 1
            if not args.keep_going or exit_code == 130:
                break
    print(f'Suite summary: {output / "summary.csv"}', flush=True)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
