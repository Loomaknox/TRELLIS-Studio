"""Regression checks for partial installation, rollback and owned directories."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.install_facial_head import claim, location, remove
from installer.facial_head_lock import component_lock


class RollbackTests(unittest.TestCase):
    def test_partial_install_and_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            component = location(root)
            other_model = root / '.tools' / 'hi3d' / 'model'
            other_model.parent.mkdir(parents=True)
            other_model.write_bytes(b'keep')
            glb = root / 'outputs' / 'original.glb'
            glb.parent.mkdir()
            glb.write_bytes(b'keep')
            claim(component)
            (component / 'partial.pth').write_bytes(b'partial')
            self.assertTrue(remove(root))
            self.assertFalse(component.exists())
            self.assertFalse(remove(root))
            self.assertEqual(other_model.read_bytes(), b'keep')
            self.assertEqual(glb.read_bytes(), b'keep')

    def test_preserves_unrecognized_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            component = location(root)
            component.mkdir(parents=True)
            with self.assertRaises(RuntimeError):
                claim(component)
            with self.assertRaises(RuntimeError):
                remove(root)
            self.assertTrue(component.is_dir())

    @unittest.skipUnless(os.name == 'nt', 'Windows mutex')
    def test_busy_runtime_cannot_be_removed(self):
        with tempfile.TemporaryDirectory() as temp, component_lock(temp):
            probe = subprocess.run([sys.executable, '-B', '-c',
                'import sys; from installer.facial_head_lock import component_lock; '
                'component_lock(sys.argv[1]).__enter__()', temp],
                cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(probe.returncode, 0)
            self.assertIn('component is busy', probe.stderr)


if __name__ == '__main__':
    unittest.main()
