#!/usr/bin/env python3
"""Manage local SimCXL guest assets. No simulator builds or runs are implicit."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
from html.parser import HTMLParser
import http.cookiejar
import io
import ipaddress
import json
import lzma
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
IMAGES = HERE / "images"
LOCAL = HERE / "local"
ASSETS = json.loads((HERE / "assets.json").read_text())


def run(command, **kwargs):
    print("+ " + __import__('shlex').join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.fields = {}
        self.active = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.active = attrs.get('id') == 'download-form'
            if self.active:
                self.action = attrs.get('action')
        elif tag == 'input' and self.active and 'name' in attrs:
            self.fields[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.active = False


def fetch_asset(kind):
    info = ASSETS[kind]
    IMAGES.mkdir(exist_ok=True)
    target = IMAGES / info['name']
    receipt = target.with_name(target.name + '.json')
    if target.exists():
        if not receipt.exists():
            raise ValueError(f'{target} exists without a download receipt; move it aside or verify/import it manually')
        recorded = json.loads(receipt.read_text())
        if target.stat().st_size != info['size_bytes'] or digest(target) != recorded['sha256']:
            raise ValueError(f'Existing asset failed integrity verification: {target}')
        print(f'Verified existing {target}')
        return
    part = target.with_name(target.name + '.part')
    if part.exists():
        raise ValueError(f'Incomplete download exists: {part}. Move it aside before retrying.')
    url = 'https://drive.usercontent.google.com/download?' + urllib.parse.urlencode(
        {'id': info['drive_id'], 'export': 'download', 'confirm': 't'})
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    response = None
    for _ in range(3):
        response = opener.open(url, timeout=60)
        if 'text/html' not in response.headers.get('Content-Type', ''):
            break
        form = DownloadForm()
        form.feed(response.read(2 * 1024 * 1024).decode('utf-8', errors='replace'))
        response.close()
        if not form.action:
            raise ValueError('Google Drive did not return a download. Check sharing/quota in the official folder: ' + ASSETS['folder'])
        action = urllib.parse.urljoin(url, form.action)
        parsed = urllib.parse.urlsplit(action)
        if parsed.scheme != 'https' or parsed.hostname not in ('drive.google.com', 'drive.usercontent.google.com'):
            raise ValueError('Unexpected download-confirmation destination')
        url = action + '?' + urllib.parse.urlencode(form.fields)
    else:
        raise ValueError('Download confirmation did not complete')
    size, h = 0, hashlib.sha256()
    last = time.monotonic()
    with response, part.open('xb') as f:
        while True:
            block = response.read(4 * 1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > info['size_bytes']:
                raise ValueError('Upstream asset size changed; review assets.json before accepting it')
            f.write(block)
            h.update(block)
            if time.monotonic() - last >= 10:
                print(f'{info["name"]}: {size / info["size_bytes"]:.1%}', flush=True)
                last = time.monotonic()
    if size != info['size_bytes']:
        raise ValueError(f'Incomplete or changed asset: expected {info["size_bytes"]}, received {size}')
    with part.open('rb') as f:
        magic = f.read(6)
    if kind == 'kernel' and not magic.startswith(b'\x7fELF'):
        raise ValueError('Downloaded kernel is not an ELF image')
    if kind == 'disk' and magic != b'\xfd7zXZ\x00':
        raise ValueError('Downloaded disk is not an XZ archive')
    checksum = h.hexdigest()
    if info.get('publisher_sha256') and checksum != info['publisher_sha256']:
        raise ValueError('Publisher checksum mismatch')
    part.rename(target)
    receipt.write_text(json.dumps({'source_folder': ASSETS['folder'], 'drive_id': info['drive_id'],
        'size_bytes': size, 'sha256': checksum, 'downloaded_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'checksum_origin': 'locally calculated; upstream did not publish SHA-256'}, indent=2) + '\n')
    print(f'Downloaded and verified format/size: {target}')


@contextmanager
def extraction_lock():
    IMAGES.mkdir(exist_ok=True)
    with (IMAGES / '.base-extraction.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another setup process is extracting base.img; wait for it to finish') from None
        yield


def preserve_partial_extraction():
    """Caller must hold extraction_lock; incomplete images are never reused."""
    part = IMAGES / 'base.img.part'
    if part.exists():
        backup = part.with_name(f'{part.name}.interrupted-{time.time_ns()}')
        part.rename(backup)
        print(f'Preserved interrupted extraction: {backup}', flush=True)


def unpack():
    with extraction_lock():
        return _unpack_locked()


def _unpack_locked():
    archive = IMAGES / ASSETS['disk']['name']
    base = IMAGES / 'base.img'
    if base.exists():
        if not (IMAGES / 'base.img.json').exists():
            raise ValueError('base.img exists without a completed extraction receipt')
        return base
    if not archive.exists():
        raise ValueError('Fetch the disk asset first')
    # Verify the downloaded archive before decompression.
    fetch_asset('disk')
    preserve_partial_extraction()
    part = IMAGES / 'base.img.part'
    size = 0
    last = time.monotonic()
    print(f'Extracting {archive.name} into {part.name} (starting from the beginning)', flush=True)
    with lzma.open(archive, 'rb') as src, part.open('xb') as dst:
        while True:
            block = src.read(4 * 1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > 200 * 1024**3:
                raise ValueError('Unexpected raw image size above 200 GiB')
            if block.count(0) == len(block):
                dst.seek(len(block), os.SEEK_CUR)
            else:
                dst.write(block)
            if time.monotonic() - last >= 10:
                print(f'Extracted {size / 1024**3:.1f} GiB', flush=True)
                last = time.monotonic()
        dst.truncate(size)
    part.rename(base)
    (IMAGES / 'base.img.json').write_text(json.dumps({'archive': archive.name,
        'archive_sha256': json.loads(archive.with_name(archive.name + '.json').read_text())['sha256'],
        'size_bytes': size}, indent=2) + '\n')
    return base


def source_archive(study_root=None):
    """Archive pinned source revisions, never imported venvs, binaries, or results."""
    LOCAL.mkdir(exist_ok=True)
    sources = json.loads((HERE / 'upstreams.json').read_text())
    archive = LOCAL / 'sources.tar'
    with tempfile.TemporaryDirectory(dir=LOCAL) as tmp:
        combined = Path(tmp) / 'combined.tar'
        with tarfile.open(combined, 'w') as output:
            for name, item in sources.items():
                if study_root:
                    repo = study_root / item['source_path']
                else:
                    repo = LOCAL / 'upstreams' / name
                    if not repo.exists():
                        repo.parent.mkdir(parents=True, exist_ok=True)
                        run(['git', 'clone', '--no-checkout', '--filter=blob:none', item['url'], repo])
                    run(['git', '-C', repo, 'fetch', '--depth=1', 'origin', item['commit']])
                commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', item['commit'] + '^{commit}'], text=True).strip()
                if commit != item['commit']:
                    raise ValueError('Source revision mismatch for ' + name)
                part = Path(tmp) / (name + '.tar')
                run(['git', '-C', repo, 'archive', '--format=tar', '--prefix=' + name + '/',
                     '--output=' + str(part), commit])
                with tarfile.open(part) as incoming:
                    for member in incoming:
                        output.addfile(member, incoming.extractfile(member) if member.isfile() else None)
        combined.replace(archive)
    (LOCAL / 'sources.json').write_text(json.dumps({'revisions': sources, 'sha256': digest(archive)}, indent=2) + '\n')
    print('Source archive: ' + str(archive))


def tools_required():
    return ('virt-customize', 'guestfish', 'qemu-img', 'cp', 'git')


def check_appliance_kernel():
    """Catch unreadable host kernels before copying or extracting large images."""
    kernel = os.environ.get('SUPERMIN_KERNEL')
    if kernel:
        if not Path(kernel).is_file() or not os.access(kernel, os.R_OK):
            raise ValueError(f'SUPERMIN_KERNEL is not a readable file: {kernel}')
        modules = os.environ.get('SUPERMIN_MODULES')
        if modules and not Path(modules).is_dir():
            raise ValueError(f'SUPERMIN_MODULES directory does not exist: {modules}')
    elif not os.environ.get('LIBGUESTFS_PATH'):
        kernels = list(Path('/boot').glob('vmlinuz-*'))
        if kernels and not any(os.access(p, os.R_OK) for p in kernels):
            raise ValueError('Host /boot/vmlinuz-* kernels are unreadable. Copy a host kernel '
                             'to guest/local with sudo install -m 0644, then set SUPERMIN_KERNEL '
                             'and matching SUPERMIN_MODULES; see guest/README.md.')


def doctor():
    missing = []
    for tool in tools_required():
        path = shutil.which(tool)
        print(f'{tool}: {path or "MISSING"}')
        if not path:
            missing.append(tool)
    print(f'Free disk space: {shutil.disk_usage(HERE).free / 1024**3:.1f} GiB')
    print(f'KVM accessible: {os.access("/dev/kvm", os.R_OK | os.W_OK)} (atomic boot is supported but slower)')
    for name in ('vmlinux', 'parsec.img.xz', 'base.img', 'btp.img'):
        print(f'{name}: {"present" if (IMAGES / name).is_file() else "not installed"}')
    if missing:
        print('Host prerequisites: sudo apt-get install libguestfs-tools qemu-system-x86 qemu-utils git xz-utils')
    try:
        check_appliance_kernel()
    except ValueError as exc:
        print(f'libguestfs prerequisite: {exc}')
        return False
    return not missing


def provisioning_resolver():
    """Use the direct backend's QEMU DNS forwarder unless explicitly overridden."""
    override = os.environ.get('SIMCXL_DNS_NAMESERVERS')
    candidates = [override.split() if override else ['169.254.2.3']]
    for values in candidates:
        servers = []
        for value in values:
            address = ipaddress.ip_address(value)
            if address.version == 4 and not (address.is_loopback or address.is_unspecified or address.is_multicast):
                if value not in servers:
                    servers.append(value)
        if servers:
            return ''.join(f'nameserver {server}\n' for server in servers[:3]) + 'options timeout:3 attempts:2\n'
    raise ValueError('No usable IPv4 DNS servers found. Set SIMCXL_DNS_NAMESERVERS to reachable DNS IPs.')


def make_payload(profile):
    resolver = provisioning_resolver().encode()
    target = LOCAL / 'payload.tar'
    with tarfile.open(target, 'w') as tar:
        tar.add(HERE / 'payload', arcname='btp')
        info = tarfile.TarInfo('btp/config/provision-resolv.conf')
        info.size = len(resolver)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(resolver))
        # Build m5 against the guest libc, not the host's relocated environment.
        def exclude_build(info):
            return None if any(p in ('build', '__pycache__', '.git') for p in Path(info.name).parts) else info
        tar.add(REPO / 'util/m5', arcname='btp/simcxl/util/m5', filter=exclude_build)
        tar.add(REPO / 'include/gem5', arcname='btp/simcxl/include/gem5', filter=exclude_build)
    return target


def repair_llama(jobs):
    """Rebuild only the installed Llama target; no downloads or image copies."""
    target = IMAGES / 'btp.img'
    receipt = IMAGES / 'btp.img.json'
    current = json.loads(receipt.read_text())
    if current['profile'] != 'all':
        raise ValueError('Llama repair requires a prepared all-workload image')
    if not shutil.which('fuser'):
        raise ValueError('Install psmisc for the image-in-use check')
    with (IMAGES / '.preparation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another setup process is preparing the guest disk') from None
        if subprocess.run(['fuser', '-s', str(target)]).returncode != 1:
            raise ValueError('Guest image may be in use; stop its simulations before repair')
        script = HERE / 'payload/repair-llama.sh'
        run(['virt-customize', '--format', 'raw', '-a', target,
             '--memsize', '4096', '--smp', str(jobs), '--no-network',
             '--upload', str(script) + ':/opt/btp/repair-llama.sh',
             '--run-command', 'bash /opt/btp/repair-llama.sh ' + str(jobs)],
            env=dict(os.environ, LIBGUESTFS_BACKEND='direct'))
        current.setdefault('repairs', []).append({
            'repair': 'llama-disable-bmi2', 'script_sha256': digest(script),
            'time_unix': time.time(), 'simulator_validated': False})
        receipt.write_text(json.dumps(current, indent=2) + '\n')


def prepare(profile, jobs, resume=False, ensure_all=False, models_only=False):
    IMAGES.mkdir(exist_ok=True)
    with (IMAGES / '.preparation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another setup process is preparing the guest disk') from None
        return _prepare_locked(profile, jobs, resume, ensure_all, models_only)


def _prepare_locked(profile, jobs, resume, ensure_all=False, models_only=False):
    target = IMAGES / 'btp.img'
    receipt = IMAGES / 'btp.img.json'
    backup = IMAGES / 'btp.basic.img'
    upgrade = False
    if ensure_all:
        if profile != 'all':
            raise ValueError('ensure-all requires profile all')
        if target.exists():
            current = json.loads(receipt.read_text())['profile']
            if current == 'all':
                print('All-workload guest image is already prepared', flush=True)
                return
            if current != 'basic':
                raise ValueError(f'Cannot upgrade unknown guest profile {current}')
            if backup.exists() or backup.with_suffix('.img.json').exists():
                raise ValueError('btp.basic.img backup already exists; move it aside before upgrading')
            upgrade = True
    if not doctor():
        raise ValueError('Resolve the host prerequisites reported above, then repeat prepare')
    if not (LOCAL / 'sources.tar').exists():
        raise ValueError('Run sources first, optionally with --study-root')
    base = unpack()
    work = IMAGES / ('btp.all.preparing.img' if ensure_all else 'btp.preparing.img')
    if ensure_all:
        resume = work.is_file()
    if models_only and (profile != 'all' or not resume or not work.is_file()):
        raise ValueError('--models-only requires an existing partial all-profile image with completed builds')
    if target.exists() and not upgrade:
        raise ValueError('A prepared disk already exists; move it aside before creating another')
    if resume and not work.is_file():
        raise ValueError('No btp.preparing.img exists to resume; omit --resume')
    if work.exists() and not resume:
        raise ValueError('A partial working disk exists; use prepare --resume to retry it')
    payload = make_payload(profile)
    if resume:
        print(f'Retrying provisioning in {work}; no disk copy', flush=True)
    else:
        # Reflinks or sparse copying preserve the unmodified upstream base image.
        run(['cp', '--reflink=auto', '--sparse=always', target if upgrade else base, work])
    env = dict(os.environ, LIBGUESTFS_BACKEND='direct')
    run(['virt-customize', '--format', 'raw', '-a', work, '--memsize', '4096', '--smp', str(jobs),
         '--network', '--tar-in', str(payload) + ':/opt', '--mkdir', '/opt/btp/upstreams',
         '--tar-in', str(LOCAL / 'sources.tar') + ':/opt/btp/upstreams',
         '--run-command', f'bash /opt/btp/provision.sh {profile} {jobs} ' +
         ('models' if models_only else 'full')], env=env)
    inspected = subprocess.check_output(['guestfish', '--ro', '--format=raw', '-a', str(work),
                                          'run', ':', 'inspect-os'], text=True, env=env).strip().splitlines()
    if len(inspected) != 1 or not re.fullmatch(r'/dev/sda\d*', inspected[0]):
        raise ValueError(f'Expected one directly mounted Linux root partition; inspect manually: {inspected}')
    info = {'root_device': inspected[0], 'profile': profile, 'kernel': 'vmlinux',
            'base_receipt': json.loads((IMAGES / 'base.img.json').read_text()),
            'sources': json.loads((LOCAL / 'sources.json').read_text()),
            'prepared_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    pending_receipt = work.with_suffix('.img.json')
    pending_receipt.write_text(json.dumps(info, indent=2) + '\n')
    if upgrade:
        target.rename(backup)
        receipt.rename(backup.with_suffix('.img.json'))
        print(f'Preserved basic guest image: {backup}', flush=True)
    work.rename(target)
    pending_receipt.rename(receipt)
    print('Prepared ' + str(target) + '; guest boot validation is still required.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    download = commands.add_parser('fetch')
    download.add_argument('--only', choices=['kernel', 'disk', 'all'], default='all')
    commands.add_parser('unpack')
    sources = commands.add_parser('sources')
    sources.add_argument('--study-root', type=Path)
    repair = commands.add_parser('repair-llama', help='Rebuild installed Llama without unsupported BMI2; stop simulations first')
    repair.add_argument('--jobs', type=int, default=2)
    prep = commands.add_parser('prepare')
    prep.add_argument('--profile', choices=['basic', 'all'], default='basic')
    prep.add_argument('--jobs', type=int, default=2)
    prep.add_argument('--resume', action='store_true',
                      help='Retry provisioning in the existing btp.preparing.img without copying the base')
    full = commands.add_parser('ensure-all', help='Prepare all workloads, preserving an existing basic image')
    full.add_argument('--jobs', type=int, default=2)
    full.add_argument('--models-only', action='store_true',
                      help='Resume a partial all image at model downloads, skipping completed software builds')
    args = parser.parse_args()
    IMAGES.mkdir(exist_ok=True)
    LOCAL.mkdir(exist_ok=True)
    if args.command == 'doctor':
        raise SystemExit(0 if doctor() else 1)
    elif args.command == 'fetch':
        for kind in ('kernel', 'disk') if args.only == 'all' else (args.only,):
            fetch_asset(kind)
    elif args.command == 'unpack':
        print(unpack())
    elif args.command == 'sources':
        source_archive(args.study_root.resolve() if args.study_root else None)
    elif args.command in ('prepare', 'ensure-all', 'repair-llama'):
        if not 1 <= args.jobs <= 16:
            parser.error('--jobs must be between 1 and 16')
        if args.command == 'repair-llama':
            repair_llama(args.jobs)
        elif args.command == 'ensure-all':
            prepare('all', args.jobs, ensure_all=True, models_only=args.models_only)
        else:
            prepare(args.profile, args.jobs, args.resume)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
