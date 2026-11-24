"""Focused setup checks for CPU finishing dependencies; no application install."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import importlib.util
import ast
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('studio_setup', ROOT / 'installer/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class InstallerTests(TestCase):
    def test_workshop_includes_pin_and_preserves_configuration(self):
        tree=ast.parse((ROOT / 'baked_game_copy.py').read_text(encoding='utf-8'))
        version=next(node.value.value for node in tree.body if isinstance(node,ast.Assign)
                     and any(isinstance(target,ast.Name) and target.id=='PYMESHLAB_VERSION' for target in node.targets))
        self.assertIn('pymeshlab=='+version, (ROOT / 'requirements-windows.txt').read_text().splitlines())
        metadata=json.loads((ROOT / 'docs/DEPENDENCIES.json').read_text(encoding='utf-8'))
        entries=[entry for entry in metadata['packages'] if entry['name']=='pymeshlab']
        self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['version'],version)
        self.assertIn('requirements-windows.txt',entries[0]['used_by'])
        with TemporaryDirectory(prefix='game-copy-setup-') as directory:
            root = Path(directory)
            (root / 'installer/locks').mkdir(parents=True)
            workshop = root / 'installer/locks/workshop-win-cp311.txt'
            mcp = root / 'installer/locks/mcp-win-cp311.txt'
            for name in ('requirements-windows.txt', 'requirements-mcp-lock.txt', 'installer/setup.py',
                         workshop.relative_to(root), mcp.relative_to(root)):
                (root / name).write_bytes((ROOT / name).read_bytes())
            (root / 'config').mkdir()
            personal = root / 'config/server.json'
            personal.write_bytes(b'{"fixture":"preserve"}')
            python = root / '.venv/Scripts/python.exe'
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'ensure_venvs', return_value=python), \
                 patch.object(setup, 'run') as run, patch.object(setup, 'ensure_web'), patch.object(setup, 'verify') as verify:
                setup.install_workshop(root / 'uv.exe')
            flags = ('--only-binary', ':all:', '--require-hashes', '--no-deps', '-r')
            self.assertEqual([call.args for call in run.call_args_list], [
                (root / 'uv.exe', 'pip', 'install', '--python', python, *flags, workshop),
                (root / 'uv.exe', 'pip', 'install', '--python', root / '.mcp-venv/Scripts/python.exe', *flags, mcp),
            ])
            pins = [line.split()[0] for line in workshop.read_text().splitlines() if line and not line.startswith('#')]
            self.assertEqual(pins.count('pymeshlab==' + version), 1)
            self.assertIn('numpy==2.2.6', pins)
            self.assertFalse(any('torch' in pin or 'cuda' in pin for pin in pins))
            verify.assert_called_once_with(rig=False, workshop_only=True)
            self.assertEqual(personal.read_bytes(), b'{"fixture":"preserve"}')
            marker = json.loads((root / '.studio-workshop-ready').read_text())
            for lock in (workshop, mcp):
                self.assertEqual(marker[lock.relative_to(root).as_posix()], setup.digest(lock))
            workshop.write_text('changed-pin\n')
            self.assertNotEqual(marker['installer/locks/workshop-win-cp311.txt'], setup.digest(workshop))

    def test_rejected_workshop_lock_stops_mcp_install_and_preserves_marker(self):
        with TemporaryDirectory(prefix='game-copy-pin-') as directory:
            root = Path(directory)
            marker = root / '.studio-workshop-ready'
            marker.write_bytes(b'previous installation')
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'ensure_venvs'), \
                 patch.object(setup, 'run', side_effect=subprocess.CalledProcessError(1, 'uv')) as run, \
                 self.assertRaises(subprocess.CalledProcessError):
                setup.install_workshop(root / 'uv.exe')
            run.assert_called_once()
            self.assertEqual(run.call_args.args[-1], root / 'installer/locks/workshop-win-cp311.txt')
            self.assertEqual(marker.read_bytes(), b'previous installation')

    def test_verification_modes_keep_gpu_optional(self):
        with patch.object(setup, 'run') as run, patch.object(setup, 'bundled_web', return_value=True), \
             patch('installer.install_segmentation.verify') as verify_segmentation:
            setup.verify(rig=False, workshop_only=True)
            verify_segmentation.assert_not_called()
            calls = [call.args for call in run.call_args_list]
            self.assertTrue(any(setup.GAME_COPY_CHECK in args for args in calls))
            self.assertFalse(any(ROOT / 'gpu_runtime.py' in args for args in calls))
        with patch.object(setup, 'run') as run, patch.object(setup, 'bundled_web', return_value=True), \
             patch('installer.install_segmentation.verify') as verify_segmentation:
            setup.verify(rig=False)
            verify_segmentation.assert_called_once_with(ROOT)
            self.assertTrue(any(ROOT / 'gpu_runtime.py' in call.args for call in run.call_args_list))
            self.assertTrue(any(setup.GAME_COPY_CHECK in call.args for call in run.call_args_list))

    def test_native_smoke_with_missing_optional_blender(self):
        if importlib.util.find_spec('pymeshlab') is None:
            self.skipTest('Install the pinned Workshop dependency for the native smoke check.')
        env = {**os.environ, 'TRELLIS_BLENDER': str(ROOT / 'not-a-blender-executable.exe')}
        result = subprocess.run([sys.executable, '-c', setup.GAME_COPY_CHECK], cwd=ROOT, env=env,
                                capture_output=True, text=True, check=True, timeout=45)
        self.assertIn('CPU reduction check passed', result.stdout)
        self.assertIn('Workshop ready without Blender', result.stdout)


if __name__ == '__main__':
    main()
