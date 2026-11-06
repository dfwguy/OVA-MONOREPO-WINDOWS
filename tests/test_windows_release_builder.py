"""Release integrity, reproducibility and private/path boundary regressions."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('windows_release_builder', Path(__file__).resolve().parents[1] / 'tools/build_windows_release.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class ReleaseBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.root = self.parent / 'source'
        self.root.mkdir()
        (self.root / 'README.md').write_text('fixture source\n')
        (self.root / 'tool.py').write_text('print("fixture")\n')

    def test_deterministic_zip_manifest_and_exclusions(self):
        for folder in ['.git', 'artifacts', '__pycache__', 'node_modules', '.venv']:
            (self.root / folder).mkdir()
            (self.root / folder / 'ignored.txt').write_text('excluded\n')
        first, second = self.parent / 'first.zip', self.parent / 'second.zip'
        a = BUILDER.build(self.root, first, strict_layout=False)
        b = BUILDER.build(self.root, second, strict_layout=False)
        self.assertEqual(a['sha256'], b['sha256'])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(2, BUILDER.verify(first)['verified_payload_files'])
        with zipfile.ZipFile(first) as archive:
            manifest = json.loads(archive.read(BUILDER.MANIFEST_NAME))
            self.assertEqual(['README.md', 'tool.py'], [row['path'] for row in manifest['files']])
            self.assertTrue(all(info.date_time == BUILDER.FIXED_DATE for info in archive.infolist()))

    def test_modified_payload_is_rejected(self):
        original, modified = self.parent / 'original.zip', self.parent / 'modified.zip'
        BUILDER.build(self.root, original, strict_layout=False)
        with zipfile.ZipFile(original) as source, zipfile.ZipFile(modified, 'w') as target:
            for info in source.infolist():
                target.writestr(info, b'tampered\n' if info.filename == 'tool.py' else source.read(info))
        with self.assertRaisesRegex(ValueError, 'payload integrity mismatch'):
            BUILDER.verify(modified)

    def test_secret_runtime_path_is_rejected(self):
        (self.root / '.env').write_text('synthetic-fixture-only\n')
        with self.assertRaisesRegex(ValueError, 'Private/runtime credential path'):
            BUILDER.inspect_source(self.root, strict_layout=False)

    def test_normalized_case_collision_and_traversal_paths_rejected(self):
        for path in ['../escape', '/absolute', 'a//b', 'a/./b', 'a\\b', 'C:/drive', 'NUL.txt', 'trailing.']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                BUILDER.validate_path(path)
        prefixes = {}
        BUILDER.validate_path('Example/one.txt', prefixes)
        with self.assertRaisesRegex(ValueError, 'case-colliding'):
            BUILDER.validate_path('example/two.txt', prefixes)

    @unittest.skipUnless(os.name == 'posix', 'fixture symlink creation requires local privilege')
    def test_safe_file_symlink_materialized_and_external_target_rejected(self):
        alias = self.root / 'CLAUDE.md'
        alias.symlink_to('README.md')
        archive = self.parent / 'links.zip'
        BUILDER.build(self.root, archive, strict_layout=False)
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read('README.md'), z.read('CLAUDE.md'))
            manifest = json.loads(z.read(BUILDER.MANIFEST_NAME))
            row = next(row for row in manifest['files'] if row['path'] == 'CLAUDE.md')
            self.assertEqual('internal-file-symlink-materialized', row['source_kind'])
        alias.unlink()
        outside = self.parent / 'outside.txt'
        outside.write_text('outside fixture')
        alias.symlink_to('../outside.txt')
        with self.assertRaisesRegex(ValueError, 'External or non-file symlink'):
            BUILDER.inspect_source(self.root, strict_layout=False)

    @unittest.skipUnless(os.name == 'posix', 'fixture symlink creation requires local privilege')
    def test_directory_and_looping_symlinks_rejected(self):
        folder = self.root / 'folder'
        folder.mkdir()
        (self.root / 'directory-link').symlink_to('folder', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Directory symlinks'):
            BUILDER.inspect_source(self.root, strict_layout=False)
        (self.root / 'directory-link').unlink()
        (self.root / 'first-link').symlink_to('second-link')
        (self.root / 'second-link').symlink_to('first-link')
        with self.assertRaisesRegex(ValueError, 'Broken/looping'):
            BUILDER.inspect_source(self.root, strict_layout=False)


if __name__ == '__main__':
    unittest.main()
