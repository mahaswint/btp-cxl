"""Short setup tests: no downloads, image builds, or simulator runs."""
import importlib.util
import io
import json
import lzma
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('guest_setup', Path(__file__).parents[2] / 'guest/setup.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class GuestSetupTest(unittest.TestCase):
    def test_llama_repair_rejects_in_use_image(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
                patch.object(m.shutil, 'which', return_value='/usr/bin/fuser'), \
                patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                patch.object(m, 'run') as run:
            (Path(temp) / 'btp.img.json').write_text('{"profile":"all"}')
            with self.assertRaisesRegex(ValueError, 'in use'):
                m.repair_llama(2)
            run.assert_not_called()

    def test_llama_repair_updates_receipt_only_after_success(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
                patch.object(m.shutil, 'which', return_value='/usr/bin/fuser'), \
                patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), \
                patch.object(m, 'run') as run:
            receipt = Path(temp) / 'btp.img.json'
            receipt.write_text('{"profile":"all"}')
            run.side_effect = RuntimeError('build failed')
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                m.repair_llama(2)
            self.assertNotIn('repairs', json.loads(receipt.read_text()))
            run.side_effect = None
            m.repair_llama(2)
            self.assertIn('--no-network', run.call_args.args[0])
            self.assertEqual(json.loads(receipt.read_text())['repairs'][0]['repair'], 'llama-disable-bmi2')

    def test_all_upgrade_preserves_basic_until_provisioning_succeeds(self):
        for fail in (True, False):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as temp, \
                 patch.object(m, 'IMAGES', Path(temp)), patch.object(m, 'LOCAL', Path(temp)), \
                 patch.object(m, 'doctor', return_value=True), \
                 patch.object(m, 'unpack', return_value=Path(temp) / 'base.img'), \
                 patch.object(m, 'make_payload', return_value=Path(temp) / 'payload.tar'), \
                 patch.object(m.subprocess, 'check_output', return_value='/dev/sda1\n'):
                root = Path(temp)
                target = root / 'btp.img'
                target.write_bytes(b'basic image')
                (root / 'btp.img.json').write_text('{"profile": "basic"}')
                for name in ('sources.json', 'base.img.json'):
                    (root / name).write_text('{}')
                (root / 'sources.tar').touch()
                def fake_run(command, **kwargs):
                    self.assertEqual(target.read_bytes(), b'basic image')
                    if command[0] == 'cp':
                        Path(command[-1]).write_bytes(Path(command[-2]).read_bytes())
                    elif fail:
                        raise RuntimeError('provision failed')
                    else:
                        (root / 'btp.all.preparing.img').write_bytes(b'all image')
                with patch.object(m, 'run', side_effect=fake_run):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'provision failed'):
                            m.prepare('all', 2, ensure_all=True)
                        self.assertEqual(target.read_bytes(), b'basic image')
                        self.assertFalse((root / 'btp.basic.img').exists())
                    else:
                        m.prepare('all', 2, ensure_all=True)
                        self.assertEqual(target.read_bytes(), b'all image')
                        self.assertEqual((root / 'btp.basic.img').read_bytes(), b'basic image')
                        self.assertEqual(json.loads((root / 'btp.img.json').read_text())['profile'], 'all')
                        self.assertEqual(json.loads((root / 'btp.basic.img.json').read_text())['profile'], 'basic')

    def test_resolver_install_handles_missing_and_symlinked_files_on_retry(self):
        script = m.HERE / 'payload/configure-resolver.sh'
        for initial in ('missing', 'regular', 'dangling', 'symlink'):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source, dest, backup = (root / name for name in ('source', 'resolv.conf', 'backup'))
                source.write_text('nameserver 192.0.2.1\n')
                target = root / 'target'
                if initial == 'regular':
                    dest.write_text('original')
                elif initial in ('dangling', 'symlink'):
                    dest.symlink_to(target)
                    if initial == 'symlink':
                        target.write_text('original')
                command = ['bash', str(script), str(source), str(dest), str(backup)]
                subprocess.run(command, check=True)
                self.assertFalse(dest.is_symlink())
                self.assertEqual(dest.read_text(), source.read_text())
                if initial == 'missing':
                    self.assertFalse(backup.exists())
                elif initial == 'regular':
                    self.assertEqual(backup.read_text(), 'original')
                else:
                    self.assertTrue(backup.is_symlink())
                    self.assertEqual(target.exists(), initial == 'symlink')
                    if target.exists():
                        self.assertEqual(target.read_text(), 'original')
                source.write_text('nameserver 192.0.2.2\n')
                subprocess.run(command, check=True)
                self.assertEqual(dest.read_text(), source.read_text())
                if initial == 'regular':
                    self.assertEqual(backup.read_text(), 'original')

    def test_resume_uses_existing_disk_without_copying(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
             patch.object(m, 'LOCAL', Path(temp)), patch.object(m, 'doctor', return_value=True), \
             patch.object(m, 'unpack', return_value=Path(temp) / 'base.img'), \
             patch.object(m, 'make_payload', return_value=Path(temp) / 'payload.tar'), \
             patch.object(m, 'run', side_effect=RuntimeError('stop before actual provisioning')) as run:
            (Path(temp) / 'sources.tar').touch()
            disk = Path(temp) / 'btp.preparing.img'
            disk.write_bytes(b'existing working disk')
            with self.assertRaisesRegex(RuntimeError, 'stop before actual provisioning'):
                m.prepare('basic', 2, resume=True)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args.args[0][0], 'virt-customize')
            self.assertEqual(disk.read_bytes(), b'existing working disk')

    def test_resolver_override_excludes_loopback_and_duplicates(self):
        with patch.dict(m.os.environ, {'SIMCXL_DNS_NAMESERVERS': '127.0.0.53 172.17.1.1 172.17.1.1'}):
            self.assertEqual(m.provisioning_resolver(), 'nameserver 172.17.1.1\noptions timeout:3 attempts:2\n')

    def test_resolver_rejects_only_loopback(self):
        with patch.dict(m.os.environ, {'SIMCXL_DNS_NAMESERVERS': '127.0.0.53'}):
            with self.assertRaisesRegex(ValueError, 'No usable IPv4 DNS'):
                m.provisioning_resolver()

    def test_default_resolver_uses_appliance_forwarder(self):
        with patch.dict(m.os.environ, {}, clear=True):
            self.assertEqual(m.provisioning_resolver(), 'nameserver 169.254.2.3\noptions timeout:3 attempts:2\n')

    def test_interrupted_extraction_restarts_and_preserves_partial(self):
        data = b'complete image' + bytes(1024)
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
             patch.object(m, 'fetch_asset') as verify:
            archive = Path(temp) / m.ASSETS['disk']['name']
            archive.write_bytes(lzma.compress(data))
            archive.with_name(archive.name + '.json').write_text('{"sha256": "test"}')
            (Path(temp) / 'base.img.part').write_bytes(b'incomplete image')
            base = m.unpack()
            verify.assert_called_once_with('disk')
            self.assertEqual(base.read_bytes(), data)
            self.assertEqual(json.loads((Path(temp) / 'base.img.json').read_text())['size_bytes'], len(data))
            backups = list(Path(temp).glob('base.img.part.interrupted-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b'incomplete image')
            self.assertFalse((Path(temp) / 'base.img.part').exists())

    def test_active_extraction_blocks_retry_without_touching_partial(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
             patch.object(m, 'fetch_asset') as verify:
            part = Path(temp) / 'base.img.part'
            part.write_bytes(b'in progress')
            with m.extraction_lock():
                with self.assertRaisesRegex(ValueError, 'Another setup process'):
                    m.unpack()
            verify.assert_not_called()
            self.assertEqual(part.read_bytes(), b'in progress')

    def test_confirmation_form_ignores_unrelated_fields(self):
        form = m.DownloadForm()
        form.feed('<input name="outside" value="wrong"><form id="download-form" '
                  'action="https://drive.usercontent.google.com/download">'
                  '<input name="id" value="asset"><input name="confirm" value="t">'
                  '</form><input name="after" value="wrong">')
        self.assertEqual(form.fields, {'id': 'asset', 'confirm': 't'})
        self.assertEqual(form.action, 'https://drive.usercontent.google.com/download')

    def test_successful_download_has_receipt(self):
        data = b'\x7fELFkernel'
        response = io.BytesIO(data)
        response.headers = {'Content-Type': 'application/octet-stream'}
        class Opener:
            def open(self, *args, **kwargs):
                return response
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
             patch.dict(m.ASSETS, {'kernel': {'name': 'vmlinux', 'drive_id': 'id', 'size_bytes': len(data)}}), \
             patch.object(m.urllib.request, 'build_opener', return_value=Opener()):
            m.fetch_asset('kernel')
            receipt = json.loads((Path(temp) / 'vmlinux.json').read_text())
            self.assertEqual(receipt['sha256'], m.digest(Path(temp) / 'vmlinux'))
            m.fetch_asset('kernel')  # Existing file verified without network.
            (Path(temp) / 'vmlinux').write_bytes(b'x' * len(data))
            with self.assertRaisesRegex(ValueError, 'integrity'):
                m.fetch_asset('kernel')

    def test_incomplete_download_never_becomes_kernel(self):
        response = io.BytesIO(b'\x7fELF')
        response.headers = {'Content-Type': 'application/octet-stream'}
        class Opener:
            def open(self, *args, **kwargs):
                return response
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
             patch.dict(m.ASSETS, {'kernel': {'name': 'vmlinux', 'drive_id': 'id', 'size_bytes': 100}}), \
             patch.object(m.urllib.request, 'build_opener', return_value=Opener()):
            with self.assertRaisesRegex(ValueError, 'Incomplete'):
                m.fetch_asset('kernel')
            self.assertFalse((Path(temp) / 'vmlinux').exists())
            self.assertFalse((Path(temp) / 'vmlinux.json').exists())

    def test_unreceipted_existing_asset_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)):
            (Path(temp) / 'vmlinux').write_bytes(b'\x7fELFfake')
            with self.assertRaisesRegex(ValueError, 'without a download receipt'):
                m.fetch_asset('kernel')

    def test_wrong_binary_format_is_rejected(self):
        data = b'not-an-ELF'
        response = io.BytesIO(data)
        response.headers = {'Content-Type': 'application/octet-stream'}
        class Opener:
            def open(self, *args, **kwargs):
                return response
        with tempfile.TemporaryDirectory() as temp, patch.object(m, 'IMAGES', Path(temp)), \
             patch.dict(m.ASSETS, {'kernel': {'name': 'vmlinux', 'drive_id': 'id', 'size_bytes': len(data)}}), \
             patch.object(m.urllib.request, 'build_opener', return_value=Opener()):
            with self.assertRaisesRegex(ValueError, 'not an ELF'):
                m.fetch_asset('kernel')
            self.assertFalse((Path(temp) / 'vmlinux').exists())


if __name__ == '__main__':
    unittest.main()
