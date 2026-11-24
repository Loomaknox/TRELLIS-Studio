"""Meaningful public-package boundary and pinned download regression checks, no services."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'installer'))
from audit_public import audit
import install_caddy
from studio_model_assets import model_asset_path


class PublicPackage(unittest.TestCase):
    def test_identical_pinned_weights_share_one_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / 'installer').mkdir()
            for name in ('native-game-geometry-manifest.json', 'native-ultratex-manifest.json',
                         'pixal3d-manifest.json', 'ultratex-manifest.json'):
                path = Path('installer') / name
                (root / path).write_bytes((ROOT / path).read_bytes())
            for native, legacy, name, expected in (
                ('native-pixal3d', 'pixal3d', 'diffusion_models/pixal3d_int8_convrot.safetensors',
                 'models/native-pixal3d'),
                ('native-ultratex', 'ultratex', 'vae/flux2-vae.safetensors', 'models/native-game-texture'),
            ):
                canonical = root / expected / name
                self.assertEqual(model_asset_path(root, native, name), canonical)
                self.assertEqual(model_asset_path(root, legacy, name), canonical)
                old_root = 'models/pixal3d/models' if legacy == 'pixal3d' else 'models/ultratex'
                old_path = root / old_root / name
                old_path.parent.mkdir(parents=True)
                old_path.touch()
                self.assertEqual(model_asset_path(root, native, name), old_path)
                self.assertEqual(model_asset_path(root, legacy, name), old_path)
                canonical.parent.mkdir(parents=True)
                old_path.rename(canonical)
                self.assertEqual(model_asset_path(root, legacy, name), canonical)
                self.assertEqual(model_asset_path(root, legacy, name, directory=root / 'custom'),
                                 root / 'custom' / name)
            text = 'text_encoders/Qwen3-8B-Q6_K.gguf'
            self.assertEqual(model_asset_path(root, 'ultratex', text), root / 'models/ultratex' / text)

    def test_private_data_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('config/server.json', 'server-data/server.sqlite3', 'logs/error.log', 'cert.key',
                         'runtime/figure-master/quad_dc.py', 'models/ultratex/runtime.json'):
                self.assertTrue(audit(root, [name]))
            file = root / 'sample.py'
            file.write_text('https://personal-host.example', encoding='utf-8')
            self.assertTrue(audit(root, ['sample.py'], ['personal-host.example']))
            file.write_text('-----BEGIN ' + 'PRIVATE KEY-----', encoding='utf-8')
            self.assertTrue(audit(root, ['sample.py']))
            file.write_text('https://studio.example.com', encoding='utf-8')
            self.assertFalse(audit(root, ['sample.py']))
            self.assertTrue(audit(root, ['../sample.py']))

    def test_proxy_checksum_and_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / 'source.zip'
            executable = b'MZfixture-not-a-program'
            with zipfile.ZipFile(archive, 'w') as package:
                for name, content in {'caddy.exe': executable, 'LICENSE': b'fixture',
                                      'README.md': b'fixture', '../outside': b'never-extracted'}.items():
                    package.writestr(name, content)
            manifest = {'executable_bytes': len(executable),
                        'executable_sha256': hashlib.sha256(executable).hexdigest()}
            destination = root / 'bin'
            with patch.object(install_caddy, 'fetch'):
                install_caddy.install(destination, manifest, archive)
                self.assertTrue(install_caddy.verified(destination, manifest))
                self.assertFalse((root / 'outside').exists())
                install_caddy.install(destination, manifest, archive)
                (destination / 'caddy.exe').write_bytes(b'unexpected existing binary')
                self.assertFalse(install_caddy.verified(destination, manifest))
                with self.assertRaises(RuntimeError):
                    install_caddy.install(destination, manifest, archive)
                self.assertEqual((destination / 'caddy.exe').read_bytes(), b'unexpected existing binary')


if __name__ == '__main__':
    unittest.main()
