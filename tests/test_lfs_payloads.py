"""Retrieval boundaries and real local Git LFS clone behavior; no network."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPOSITORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lfs_payloads', REPOSITORY / 'tools/lfs_payloads.py')
PAYLOADS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PAYLOADS)


class PayloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'control/tools/example.zip'
        self.path.parent.mkdir(parents=True)
        self.data = b'fixture payload; not an executable'
        self.pointer = ('version https://git-lfs.github.com/spec/v1\noid sha256:'
                        + hashlib.sha256(self.data).hexdigest()
                        + '\nsize ' + str(len(self.data)) + '\n').encode()

    def test_materialized_offline_release_does_not_invoke_git(self):
        self.path.write_bytes(self.data)
        with patch.object(PAYLOADS.subprocess, 'run') as run:
            self.assertEqual(0, PAYLOADS.ensure_payloads(self.root, ('control',)))
        run.assert_not_called()

    def test_pointer_without_git_fails_before_download(self):
        self.path.write_bytes(self.pointer)
        with self.assertRaisesRegex(ValueError, 'complete offline release'):
            PAYLOADS.ensure_payloads(self.root, ('control',))

    def test_scoped_download_overrides_default_filters_and_checks_bytes(self):
        (self.root / '.git').mkdir()
        self.path.write_bytes(self.pointer)

        def download(argv, **kwargs):
            self.assertEqual(['git', '-C', str(self.root), 'lfs', 'pull', '--include=control/**', '--exclude='], argv)
            self.path.write_bytes(self.data)
            return subprocess.CompletedProcess(argv, 0)

        with patch.object(PAYLOADS.subprocess, 'run', side_effect=download):
            self.assertEqual(1, PAYLOADS.ensure_payloads(self.root, ('control',)))

    def test_download_failure_and_corruption_are_rejected(self):
        (self.root / '.git').mkdir()
        for mode in ('failure', 'size', 'hash'):
            self.path.write_bytes(self.pointer)

            def download(argv, **kwargs):
                if mode == 'size':
                    self.path.write_bytes(b'too short')
                elif mode == 'hash':
                    self.path.write_bytes(b'x' * len(self.data))
                return subprocess.CompletedProcess(argv, int(mode == 'failure'))

            with self.subTest(mode=mode), patch.object(PAYLOADS.subprocess, 'run', side_effect=download):
                with self.assertRaises(ValueError):
                    PAYLOADS.ensure_payloads(self.root, ('control',))

    @unittest.skipUnless(shutil.which('git') and shutil.which('git-lfs'), 'requires Git LFS')
    def test_real_clone_downloads_native_only_then_existing_operation_hydrates(self):
        upstream = self.root / 'upstream'
        upstream.mkdir()
        env = os.environ.copy()
        for name in list(env):
            if name.startswith(('GIT_CONFIG_', 'GIT_LFS_')):
                env.pop(name)
        env['GIT_CONFIG_NOSYSTEM'] = '1'
        env['GIT_CONFIG_GLOBAL'] = str(self.root / 'fixture.gitconfig')

        def git(*args, cwd=upstream):
            return subprocess.run(['git', *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)

        git('init')
        git('lfs', 'install', '--skip-repo')
        git('lfs', 'install', '--local')
        git('config', 'user.name', 'Storage fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        (upstream / '.gitattributes').write_text('*.zip filter=lfs diff=lfs merge=lfs -text\n')
        shutil.copyfile(REPOSITORY / '.lfsconfig', upstream / '.lfsconfig')
        paths = ['windows/dependencies/native.zip', 'control/windows/python.zip',
                 'control/tools/toolkit.zip', 'components/legacy/linux.zip', 'artifacts/duplicate.zip']
        for relative in paths:
            path = upstream / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('payload ' + relative).encode())
        git('add', '.')
        git('commit', '-m', 'Local LFS fixture')
        clone = self.root / 'clone'
        git('clone', str(upstream), str(clone))
        for relative in paths:
            data = (clone / relative).read_bytes()
            if relative.startswith(('windows/', 'control/windows/')):
                self.assertEqual(('payload ' + relative).encode(), data)
            else:
                self.assertTrue(PAYLOADS.POINTER.fullmatch(data), relative)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(1, PAYLOADS.ensure_payloads(clone, ('control',)))
        self.assertEqual(b'payload control/tools/toolkit.zip', (clone / paths[2]).read_bytes())
        self.assertTrue(PAYLOADS.POINTER.fullmatch((clone / paths[3]).read_bytes()))
        self.assertTrue(PAYLOADS.POINTER.fullmatch((clone / paths[4]).read_bytes()))
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(1, PAYLOADS.ensure_payloads(clone, ('control', 'components', 'windows')))
        self.assertEqual(b'payload components/legacy/linux.zip', (clone / paths[3]).read_bytes())
        self.assertTrue(PAYLOADS.POINTER.fullmatch((clone / paths[4]).read_bytes()))


if __name__ == '__main__':
    unittest.main()
