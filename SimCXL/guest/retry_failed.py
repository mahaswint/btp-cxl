#!/usr/bin/env python3
"""Recover completed reports and rerun only unsuccessful guest simulations."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

HERE = Path(__file__).resolve().parent


def guest_completed(record):
    folder = Path(record['output_dir'])
    try:
        return (json.loads((folder / 'guest-run-status.json').read_text())['completed']
                and 'exit_code=0\n' in (folder / 'workload-status.txt').read_text())
    except (OSError, KeyError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='source', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output_dir.resolve()
    original = json.loads((source / 'summary.json').read_text())
    if output.exists():
        parser.error('Choose a new output directory')
    if not 1 <= args.jobs <= 16:
        parser.error('--jobs must be between 1 and 16')
    # This recovery command preserves one measurement for each workload.
    names = [r['workload'] for r in original['runs']]
    if len(names) != len(set(names)):
        parser.error('Recovery currently requires a suite with one repetition')
    recover = [r for r in original['runs'] if r['status'] != 'completed' and guest_completed(r)]
    retry = [r['workload'] for r in original['runs'] if r['status'] != 'completed' and not guest_completed(r)]
    from run_all import save_summary
    print('Recover existing traces: ' + ', '.join(r['workload'] for r in recover), flush=True)
    print('Rerun without trial timer: ' + ', '.join(retry), flush=True)
    commands = []
    if 'llama_cpp' in retry:
        commands.append([sys.executable, str(HERE / 'setup.py'), 'repair-llama', '--jobs', str(args.jobs)])
    for record in recover:
        folder = Path(record['output_dir'])
        trace = folder / 'cxl-events.jsonl'
        commands.append([sys.executable, str(HERE.parent / 'util/cxl_metrics.py'), 'report',
            '--trace', str(trace), '--config', str(folder / 'config.json'),
            '--metadata', str(folder / 'cxl-run.json'),
            '--output', str(output / (record['workload'] + '-cxl-metrics.json'))])
    if retry:
        commands.append([sys.executable, str(HERE / 'run_all.py'), '--workloads', *retry,
            '--size', original['size'], '--keep-going', '--output-dir', str(output / 'reruns')])
    for command in commands:
        print(shlex.join(command), flush=True)
    if args.dry_run:
        return 0
    output.mkdir(parents=True)
    # Repair failure must stop before running the known-broken Llama executable.
    if 'llama_cpp' in retry:
        subprocess.run(commands.pop(0), cwd=HERE.parent, check=True)
    for command in commands:
        subprocess.run(command, cwd=HERE.parent, check=False)
    replacements = {}
    retry_summary = output / 'reruns/summary.json'
    if retry_summary.exists():
        replacements = {r['workload']: r for r in json.loads(retry_summary.read_text())['runs']}
    assembled = []
    metrics = {}
    for old in original['runs']:
        record = dict(replacements.get(old['workload'], old))
        recovered = output / (record['workload'] + '-cxl-metrics.json')
        if old in recover and recovered.exists():
            record.update(status='completed', exit_code=0, metrics_file=str(recovered),
                          recovered_from_existing_trace=True)
        path = Path(record['metrics_file'])
        if record['status'] == 'completed' and path.exists():
            report = json.loads(path.read_text())
            phases = [p for p in report['phases'] if p['metadata']['phase'] == 'workload']
            if len(phases) == 1 and phases[0]['metadata']['complete']:
                metrics[record['workload']] = {'report_file': str(path),
                    'metadata': phases[0]['metadata'], 'metrics': phases[0]['metrics']}
            else:
                record.update(status='invalid_report', exit_code=1)
        elif record['status'] == 'completed':
            record.update(status='missing_report', exit_code=1)
        assembled.append(record)
    summary = {**original, 'trial_minutes': None, 'source_suite': str(source),
               'note': 'Original successful simulations reused; retries have no trial timer.', 'runs': assembled}
    save_summary(output, summary)
    (output / 'combined-cxl-metrics.json').write_text(json.dumps(metrics, indent=2) + '\n')
    print('Combined results: ' + str(output), flush=True)
    return 0 if all(r['status'] == 'completed' for r in assembled) else 1


if __name__ == '__main__':
    raise SystemExit(main())
