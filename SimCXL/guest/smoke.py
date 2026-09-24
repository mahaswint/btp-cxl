"""Small workloads staged exclusively in each simulator's temporary disk overlay."""
import base64
import io
from pathlib import Path
import shlex
import tarfile

HERE = Path(__file__).resolve().parent
SETTINGS = {
    'memory_pilot': {'memory_MiB': 1, 'passes': 8},
    'stream': {'array_elements': 65536, 'iterations': 3},
    'pointer_chase': {'memory_MiB': 2, 'samples': 1, 'sample_microseconds': 10000},
    'ann': {'vectors': 1024, 'queries': 8, 'dimensions': 128},
    'bert': {'batch_size': 1, 'sequence_length': 8, 'warmup': 0, 'iterations': 1},
    'kmeans': {'samples': 512, 'features': 8, 'clusters': 4, 'iterations': 2},
    'dlrm': {'batch_size': 2, 'batches': 2, 'embedding_rows': [1000] * 4, 'embedding_dimensions': 16},
    'llama_cpp': {'prompt': 'Hello', 'output_tokens': 2, 'model': 'Llama-3.2-1B-Instruct-Q4_K_M.gguf'},
}


def archive_commands(files, destination):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for source, archive_name in files:
            archive.add(source, arcname=archive_name)
    encoded = base64.b64encode(data.getvalue()).decode('ascii')
    return ['mkdir -p ' + shlex.quote(destination),
            "printf '%s' " + shlex.quote(encoded) + ' | base64 -d | tar -xz -C ' +
            shlex.quote(destination)]


def runtime_setup():
    """Stage current ROI-aware launch scripts in the per-run COW disk."""
    payload = HERE / 'payload'
    commands = archive_commands([
        (payload / 'run-workload.sh', 'run-workload.sh'),
        (payload / 'src/dlrm_roi.py', 'src/dlrm_roi.py'),
    ], '/opt/btp')
    commands.append('chmod 755 /opt/btp/run-workload.sh /opt/btp/src/dlrm_roi.py')
    return commands


def boot_setup(workload):
    if workload not in SETTINGS:
        raise ValueError('Unsupported smoke workload')
    payload = HERE / 'payload'
    commands = archive_commands([
        (payload / name, name) for name in (
            'run-workload.sh', 'smoke-prepare.sh', 'src/ann_benchmark.cpp',
            'src/bert.py', 'src/dlrm_roi.py', 'src/kmeans.py')
    ], '/opt/btp/smoke')
    commands.append('bash /opt/btp/smoke/smoke-prepare.sh ' + shlex.quote(workload))
    return commands
