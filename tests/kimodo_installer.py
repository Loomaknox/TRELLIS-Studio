"""Optional installer boundaries: downloads, archives, activation and preserved settings."""
from pathlib import Path
import hashlib
import io
from contextlib import redirect_stdout
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'installer'))
import kimodo_install_common as common
import install_kimodo as installer


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {'Content-Length': str(len(data))}


class Installer(unittest.TestCase):
    def test_bridge_relays_unicode_and_exits_cleanly(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = installer.run_bridge([sys.executable, '-c', "import sys;sys.stdout.buffer.write('Stage \\u2713\\n'.encode('utf-8'))"],
                                        [sys.executable, '-c', 'pass'])
        self.assertEqual(code, 0)
        self.assertIn('Stage \u2713', output.getvalue())

    def test_manifest_identity_ignores_line_endings_and_order(self):
        first = json.loads('{\r\n"version":1,"name":"fixture"\r\n}')
        second = json.loads('{"name":"fixture", "version": 1}')
        self.assertEqual(common.manifest_digest(first), common.manifest_digest(second))
    def entry(self, content=b'correct payload'):
        return dict(filename='fixture.bin', bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                    url='https://example.invalid/fixture', cache_candidates=[])

    def test_resume_exact_range_and_idempotent_cache(self):
        content = b'correct payload'; entry = self.entry(content)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / (entry['sha256'] + '-' + entry['filename'])
            target.with_suffix('.bin.partial').write_bytes(content[:4])
            def opener(request, timeout):
                self.assertEqual(request.headers['Range'], 'bytes=4-')
                return Response(content[4:], 206, {'Content-Range': f'bytes 4-{len(content)-1}/{len(content)}', 'Content-Length': str(len(content)-4)})
            self.assertEqual(common.fetch(entry, root, opener=opener).read_bytes(), content)
            self.assertEqual(common.fetch(entry, root, opener=lambda *_a, **_k: self.fail('Redownload')), target)
            target.write_bytes(b'x' * len(content))
            with self.assertRaisesRegex(RuntimeError, 'modified'):
                common.fetch(entry, root, opener=opener)

    def test_bad_ranges_corrupt_partial_and_explicit_reuse(self):
        content = b'correct payload'; entry = self.entry(content)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); cache = root / 'cache'; cache.mkdir()
            partial = cache / (entry['sha256'] + '-fixture.bin.partial'); partial.write_bytes(content[:4])
            with self.assertRaisesRegex(RuntimeError, 'byte range'):
                common.fetch(entry, cache, opener=lambda *_a, **_k: Response(content[4:], 206, {'Content-Range': 'bytes 0-9/10'}))
            partial.write_bytes(b'x' * len(content))
            result = common.fetch(entry, cache, opener=lambda *_a, **_k: Response(content))
            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(len(list(cache.glob('*.invalid-*'))), 1)
            reuse = root / 'reuse'; reuse.mkdir(); (reuse / 'fixture.bin').write_bytes(content)
            result = common.fetch(entry, root / 'other cache', reuse, opener=lambda *_a, **_k: self.fail('Network should not be needed'))
            self.assertEqual(result.read_bytes(), content)

    def test_finite_network_retries(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(common.time, 'sleep'):
            calls = []
            def failure(*_a, **_k):
                calls.append(1)
                raise TimeoutError('offline')
            with self.assertRaisesRegex(RuntimeError, 'three attempts'):
                common.fetch(self.entry(), Path(tmp), opener=failure)
            self.assertEqual(len(calls), 3)

    def test_archive_traversal_and_modified_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive = root / 'source.zip'
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('repo/../../outside', b'never')
            entry = dict(kind='zip', strip_root=True, sha256=common.sha256(archive))
            with self.assertRaisesRegex(ValueError, 'archive entry'):
                common.extract(archive, root / 'destination', entry)
            self.assertFalse((root / 'outside').exists())
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('repo/source.cpp', b'original')
            entry['sha256'] = common.sha256(archive)
            common.extract(archive, root / 'destination', entry)
            common.extract(archive, root / 'destination', entry)
            (root / 'destination/source.cpp').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'modified'):
                common.extract(archive, root / 'destination', entry)

    def test_paths_and_licence_gate(self):
        with tempfile.TemporaryDirectory(prefix='studio space ') as tmp:
            root = Path(tmp); (root / 'app.py').write_text('')
            for name in ('../outside', '/absolute', 'C:/absolute', 'sub\\path'):
                with self.assertRaises(ValueError):common.child(root, name)
            with self.assertRaisesRegex(ValueError, 'licenses'):
                installer.install(root, 'Ubuntu', False)
            self.assertFalse((root / 'config').exists())

    def test_custom_configs_preserved_and_invalid_refused(self):
        with tempfile.TemporaryDirectory(prefix='studio space ') as tmp:
            root = Path(tmp); (root / 'app.py').write_text(''); (root / 'config').mkdir()
            path = root / 'config/generated-animation-runtime.json'
            path.write_text('{"enabled":false,"personal":"keep"}')
            before = path.read_bytes()
            with patch.object(installer.subprocess, 'run', side_effect=AssertionError('Do not install')):
                self.assertEqual(installer.install(root, 'Ubuntu', True)['configured'], False)
            self.assertEqual(path.read_bytes(), before)
            path.write_text('{"enabled":true}')
            before = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'invalid and was preserved'):
                installer.install(root, 'Ubuntu', True)
            self.assertEqual(path.read_bytes(), before)

    def test_activation_preserves_options_and_commits_last(self):
        with tempfile.TemporaryDirectory(prefix='studio space ') as tmp:
            root = Path(tmp); (root / 'config').mkdir()
            manifest = json.loads((ROOT / 'installer/kimodo-manifest.json').read_text())
            receipt = dict(installation_id=installer.installation_id(root), smoke={'frames':60}, skeleton={'names':['fixture']},
                           executable='/engine/bin/kmd-generate',library_directory='/engine/lib',motion_model='/engine/motion.gguf',text_model='/engine/text.gguf')
            path=root/'config/generated-animation-runtime.json'
            initial=dict(managed_by=installer.MANAGED_BY,enabled=False,threads=12,steps=80,timeout_seconds=2000)
            path.write_text(json.dumps(initial)); before=path.read_bytes()
            original=installer.atomic_json
            def fail_config(target, value):
                if target==path:raise OSError('Simulated disk failure')
                return original(target,value)
            with patch.object(installer,'atomic_json',side_effect=fail_config),self.assertRaises(OSError):
                installer.activate(root,receipt,manifest,'Ubuntu',8)
            self.assertEqual(path.read_bytes(),before)
            result=installer.activate(root,receipt,manifest,'Ubuntu',8)
            self.assertFalse(result['enabled']);self.assertEqual(result['threads'],12);self.assertEqual(result['steps'],80)
            before=path.read_bytes();installer.activate(root,receipt,manifest,'Ubuntu',8)
            self.assertEqual(path.read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
