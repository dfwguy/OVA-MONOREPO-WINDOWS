"""Run with native Windows Python; no site, network or GPU access is performed."""
import contextlib
import io
import warnings
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

# Keep the checksum-verified control tree unchanged under every invocation.
sys.dont_write_bytecode = True
warnings.filterwarnings('ignore', message='Duplicate name:')

ROOT = Path(os.environ.get('OVA_CONTROL_ROOT', Path(__file__).resolve().parents[1] / 'control')).resolve()

def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class ControlHelpers(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix='ova-test-'))
        self.addCleanup(lambda: shutil.rmtree(self.temp, ignore_errors=True))

    def test_authentic_release_manifest(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/verify_bundle.py'), str(ROOT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_six_toolkits_extract_on_host(self):
        archives = sorted((ROOT / 'tools').glob('*/*.zip'))
        self.assertEqual(len(archives), 6, str(archives))
        unpacker = load('unpack_toolkit')
        for index, archive in enumerate(archives):
            with self.subTest(tool=archive.parent.name):
                dest = self.temp / ('t' + str(index))
                unpacker.unpack(archive, dest)
                self.assertTrue(any(p.is_file() for p in dest.rglob('*')))
                shutil.rmtree(dest)

    def test_reject_unsafe_archive_members_before_writing(self):
        unpacker = load('unpack_toolkit')
        names = ['../escape', '/absolute', 'C:/escape', 'path\\escape', 'CON.txt', 'folder/NUL', 'a./file', 'a /file', 'a?b', './file']
        for index, name in enumerate(names):
            with self.subTest(member=name):
                archive = self.temp / ('bad' + str(index) + '.zip')
                with zipfile.ZipFile(archive, 'w') as z:
                    # ZipInfo normalizes backslashes on Windows at construction.
                    # Assign afterwards so the archive contains the actual hostile bytes.
                    member = zipfile.ZipInfo()
                    member.filename = name
                    member.orig_filename = name
                    z.writestr(member, b'fixture')
                dest = self.temp / ('bad' + str(index))
                with self.assertRaises(ValueError):
                    unpacker.unpack(archive, dest)
                self.assertFalse(dest.exists())

    def test_reject_case_collisions_and_symlinks(self):
        unpacker = load('unpack_toolkit')
        for index, members in enumerate([['A/file', 'a/other'], ['file', 'file']]):
            archive = self.temp / ('collision' + str(index) + '.zip')
            with zipfile.ZipFile(archive, 'w') as z:
                for name in members:
                    z.writestr(name, b'fixture')
            with self.assertRaises(ValueError):
                unpacker.unpack(archive, self.temp / ('collision' + str(index)))
        archive = self.temp / 'symlink.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            entry = zipfile.ZipInfo('link')
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            z.writestr(entry, '../outside')
        with self.assertRaises(ValueError):
            unpacker.unpack(archive, self.temp / 'link')

    def test_refuse_existing_destination(self):
        unpacker = load('unpack_toolkit')
        destination = self.temp / 'existing'
        destination.mkdir()
        with self.assertRaises(ValueError):
            unpacker.unpack(self.temp / 'unused.zip', destination)

    def test_manifest_rejects_tamper_unlisted_and_traversal(self):
        verifier = load('verify_bundle')
        fixture = self.temp / 'manifest'
        fixture.mkdir()
        (fixture / 'payload').write_bytes(b'changed')
        manifest = {'files': [{'path': 'payload', 'bytes': 1, 'sha256': '0' * 64}]}
        (fixture / 'FILE_MANIFEST.json').write_text(json.dumps(manifest))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(verifier.verify(fixture), 1)
        manifest['files'] = []
        (fixture / 'FILE_MANIFEST.json').write_text(json.dumps(manifest))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(verifier.verify(fixture), 1)
        manifest['files'] = [{'path': '../escape', 'bytes': 0, 'sha256': '0' * 64}]
        (fixture / 'FILE_MANIFEST.json').write_text(json.dumps(manifest))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(verifier.verify(fixture), 1)

if __name__ == '__main__':
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout, verbosity=2))
