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
sys.path.insert(0, str(ROOT / 'installer'))
from audit_public import audit
import install_caddy


class PublicPackage(unittest.TestCase):
    def test_private_data_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('config/server.json', 'server-data/server.sqlite3', 'logs/error.log', 'cert.key'):
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
