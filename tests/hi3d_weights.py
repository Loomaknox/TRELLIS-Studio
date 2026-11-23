"""Hi3D weight relocation fixtures. No downloads or GPU initialization."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from installer import install_hi3d


class Hi3dWeightMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.legacy = self.root / '.tools' / 'hi3d' / 'weights'
        self.target = self.root / 'models' / 'hi3d'
        self.config = self.root / 'config' / 'hi3d-runtime.json'
        self.value = {
            'python': str(self.root / '.venv' / 'Scripts' / 'python.exe'),
            'source': str(self.root / '.tools' / 'hi3d' / 'source'),
            'weights': str(self.legacy),
            'dependencies': [str(self.root / '.tools' / 'hi3d' / 'dependencies')],
        }
        self.name = 'Hi3Dv1.0/model.safetensors'
        self.payload = b'verified synthetic tensor payload'
        self.manifest = {'weights': [{
            'path': self.name, 'bytes': len(self.payload),
            'sha256': hashlib.sha256(self.payload).hexdigest(),
        }]}
        self.asset = self.legacy / self.name
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(self.payload)
        install_hi3d.write(self.config, self.value)

    def migrate(self):
        return install_hi3d.migrate_weights(self.root, self.manifest)

    def check_config(self, expected):
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8')), expected)

    def test_move_reuses_existing_file_with_its_hardlink_and_is_idempotent(self):
        cache = self.root / 'cache.safetensors'
        os.link(self.asset, cache)
        self.assertEqual(self.migrate(), self.target)
        self.assertFalse(self.legacy.exists())
        self.assertTrue(cache.samefile(self.target / self.name))
        self.check_config({**self.value, 'weights': str(self.target)})
        self.assertEqual(self.migrate(), self.target)

    def test_resume_after_rename_before_config_update(self):
        self.target.parent.mkdir()
        self.legacy.rename(self.target)
        self.assertEqual(self.migrate(), self.target)
        self.check_config({**self.value, 'weights': str(self.target)})

    def test_failed_configuration_write_restores_default_store(self):
        with patch.object(install_hi3d, 'write', side_effect=PermissionError('locked configuration')):
            with self.assertRaisesRegex(PermissionError, 'locked configuration'):
                self.migrate()
        self.assertEqual(self.asset.read_bytes(), self.payload)
        self.assertFalse(self.target.exists())
        self.check_config(self.value)

    def test_checksum_mismatch_leaves_files_and_config_intact(self):
        altered = b'X' + self.payload[1:]
        self.asset.write_bytes(altered)
        with self.assertRaisesRegex(RuntimeError, 'differs from the pinned download'):
            self.migrate()
        self.assertEqual(self.asset.read_bytes(), altered)
        self.assertFalse(self.target.exists())
        self.check_config(self.value)

    def test_existing_destination_and_custom_configuration_are_preserved(self):
        self.target.mkdir(parents=True)
        marker = self.target / 'existing.txt'
        marker.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'Both Hi3D weight directories exist'):
            self.migrate()
        self.check_config(self.value)
        configured = {**self.value, 'weights': str(self.root / 'custom')}
        install_hi3d.write(self.config, configured)
        with self.assertRaisesRegex(ValueError, 'custom weight directory'):
            self.migrate()
        self.assertEqual(marker.read_bytes(), b'preserve')
        self.assertEqual(self.asset.read_bytes(), self.payload)
        self.check_config(configured)

    def test_new_store_path_and_legacy_download_resume(self):
        fresh = self.root / 'fresh'
        self.assertEqual(install_hi3d.default_weights_path(fresh), fresh / 'models' / 'hi3d')
        self.assertEqual(install_hi3d.default_weights_path(self.root), self.legacy)


if __name__ == '__main__':
    unittest.main()
