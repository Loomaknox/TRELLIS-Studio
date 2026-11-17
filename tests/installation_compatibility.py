"""Regression checks for installation failures seen on Windows/Blackwell."""
from pathlib import Path
import importlib.util
import base64
import csv
import hashlib
from types import SimpleNamespace
import json
import os
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'installer'), str(ROOT / 'UniRig')]
import studio_import
import gpu_probe
import kimodo_install_linux
import unirig_blackwell


class BlenderDetection(unittest.TestCase):
    def test_explicit_path_is_authoritative(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'blender.exe'
            path.touch()
            with patch.dict(os.environ, TRELLIS_BLENDER=str(path)), patch('shutil.which') as which:
                self.assertEqual(studio_import.find_blender(), path)
                which.assert_not_called()
            path.unlink()
            with patch.dict(os.environ, TRELLIS_BLENDER=str(path)):
                self.assertIsNone(studio_import.find_blender())

    def test_path_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'blender.exe'
            path.touch()
            with patch.dict(os.environ, TRELLIS_BLENDER=''), patch('shutil.which', return_value=str(path)):
                self.assertEqual(studio_import.find_blender(), path)


class KimodoWrapper(unittest.TestCase):
    @unittest.skipUnless(shutil.which('bash') and sys.platform != 'win32', 'Requires a Linux Bash interpreter')
    def test_preserves_argv_except_rpath_link(self):
        with tempfile.TemporaryDirectory(prefix="compiler's space ") as directory:
            root = Path(directory)
            fake = root / 'zig'
            fake.write_text('#!' + sys.executable + '\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            fake.chmod(0o755)
            wrapper = root / 'zig-cxx'
            kimodo_install_linux.write_compiler_wrapper(wrapper, fake, 'c++')
            args = ['object with space.o', '-Wl,-rpath-link,/a space', '-Wl,-rpath,/keep', '-o', "output's file", '']
            result = subprocess.check_output(['bash', str(wrapper), *args], text=True)
            self.assertEqual(json.loads(result), ['c++', '-target', 'x86_64-linux-gnu.2.35', *[a for a in args if not a.startswith('-Wl,-rpath-link,')]])

    def test_both_wrappers_use_lf_and_keep_runtime_rpath(self):
        with tempfile.TemporaryDirectory() as directory:
            for compiler in ('cc', 'c++'):
                path = Path(directory) / 'wrapper'
                kimodo_install_linux.write_compiler_wrapper(path, Path("/compiler's tools/zig"), compiler)
                text = path.read_bytes()
                self.assertNotIn(b'\r', text)
                self.assertIn(b'-Wl,-rpath-link,*) ;;', text)
                self.assertIn(b'*) args+=("$arg")', text)


class UniRigChecks(unittest.TestCase):
    def test_blackwell_preflight_fails_before_package_changes(self):
        with patch.object(unirig_blackwell, 'prerequisites', side_effect=RuntimeError('missing nvcc')), \
             patch('subprocess.run') as command:
            with self.assertRaisesRegex(RuntimeError, 'missing nvcc'):
                unirig_blackwell.install(Path('/uv'), Path('/environment'))
            command.assert_not_called()

    def test_blackwell_build_uses_installed_torch_abi_and_checks_dependencies(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, TRELLIS_UNIRIG_FLASH_SOURCE='1'), \
             patch.object(unirig_blackwell, 'prerequisites'), \
             patch.object(unirig_blackwell, 'checkout', side_effect=lambda base, name: base / name), \
             patch.object(unirig_blackwell, 'patch_spconv_metadata') as metadata, \
             patch('shutil.which', return_value='/cuda/bin/nvcc'), patch('subprocess.run') as command:
            root = Path(directory)
            unirig_blackwell.install(root / 'uv', root)
            calls = [list(map(str, call.args[0])) for call in command.call_args_list]
            self.assertIn('torch==2.8.0', calls[0])
            builds = [call for call in calls if '--no-build-isolation' in call]
            self.assertEqual([Path(call[-1]).name for call in builds], ['cumm', 'spconv', 'flash-attention'])
            self.assertTrue(all('--no-deps' in call for call in builds))
            self.assertEqual(calls[-1][1:3], ['pip', 'check'])
            self.assertEqual(os.environ['FLASH_ATTN_CUDA_ARCHS'], '120')
            self.assertEqual(os.environ['CUMM_CUDA_ARCH_LIST'], '12.0')
            metadata.assert_called_once()

    def test_default_install_uses_verified_wheel_without_building_flash(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, TRELLIS_UNIRIG_FLASH_SOURCE=''), \
             patch.object(unirig_blackwell, 'prerequisites'), \
             patch.object(unirig_blackwell, 'checkout', side_effect=lambda base, name: base / name), \
             patch.object(unirig_blackwell, 'patch_spconv_metadata'), \
             patch.object(unirig_blackwell, 'flash_wheel', return_value=Path(directory)/'verified.whl') as wheel, \
             patch('shutil.which', return_value='/cuda/bin/nvcc'), patch('subprocess.run') as command:
            root = Path(directory)
            unirig_blackwell.install(root/'uv',root)
            calls = [list(map(str, call.args[0])) for call in command.call_args_list]
            self.assertEqual([Path(call[-1]).name for call in calls if '--no-build-isolation' in call], ['cumm','spconv'])
            self.assertIn(str(root/'verified.whl'),calls[-3])
            wheel.assert_called_once_with(root,root/'venv/bin/python')

    def test_tampered_flash_cache_is_preserved_and_rejected_without_network(self):
        abi = json.dumps([[3,11],'Linux','x86_64','2.8.0+cu128',True])
        with tempfile.TemporaryDirectory() as directory, patch('subprocess.check_output',return_value=abi), \
             patch('urllib.request.urlopen') as network:
            root = Path(directory)
            cache = root/'cache/downloads';cache.mkdir(parents=True)
            wheel = cache/unirig_blackwell.FLASH_WHEEL['filename']
            wheel.write_bytes(b'tampered or incomplete wheel')
            with self.assertRaisesRegex(RuntimeError,'SHA-256 mismatch'):
                unirig_blackwell.flash_wheel(root,Path('/python'))
            self.assertEqual(wheel.read_bytes(),b'tampered or incomplete wheel')
            network.assert_not_called()

    def test_flash_wheel_rejects_wrong_abi_before_network(self):
        with patch('subprocess.check_output',return_value=json.dumps([[3,12],'Linux','x86_64','2.8.0+cu128',True])), \
             patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(RuntimeError,'requires Linux x86_64'):
                unirig_blackwell.flash_wheel(Path('/unused'),Path('/python'))
            network.assert_not_called()

    def test_bpy_tag_repair_keeps_record_hash_correct_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys,'platform','linux'), \
             patch.object(sys,'version_info',(3,11,0)), patch('importlib.metadata.distribution') as installed:
            root = Path(directory);info = root/'bpy-4.2.0.dist-info';info.mkdir()
            wheel = info/'WHEEL';record = info/'RECORD'
            original = b'Wheel-Version: 1.0\nGenerator: bdist_wheel (0.38.4)\nRoot-Is-Purelib: false\nTag: cp39-cp39-manylinux_2_28_x86_64\n\n'
            wheel.write_bytes(original)
            record.write_text('bpy-4.2.0.dist-info/WHEEL,old,1\nbpy/__init__.so,keep,123\n')
            installed.return_value = SimpleNamespace(version='4.2.0',metadata={'Requires-Python':'==3.11.*'},locate_file=lambda name:root/name)
            unirig_blackwell.repair_bpy_metadata()
            content = wheel.read_bytes()
            self.assertIn(b'cp311-cp311',content)
            expected_hash = 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b'=').decode()
            rows = list(csv.reader(record.read_text().splitlines()))
            self.assertEqual(rows[0][1:],[expected_hash,str(len(content))])
            self.assertEqual(rows[1],['bpy/__init__.so','keep','123'])
            # Resume a process interrupted after WHEEL replacement but before RECORD.
            record.write_text('bpy-4.2.0.dist-info/WHEEL,old,1\nbpy/__init__.so,keep,123\n')
            unirig_blackwell.repair_bpy_metadata()
            self.assertEqual(list(csv.reader(record.read_text().splitlines()))[0][1],expected_hash)

    def test_unknown_bpy_metadata_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys,'platform','linux'), \
             patch.object(sys,'version_info',(3,11,0)), patch('importlib.metadata.distribution') as installed:
            root = Path(directory);info = root/'bpy-4.2.0.dist-info';info.mkdir()
            wheel = info/'WHEEL';wheel.write_bytes(b'unrecognized metadata')
            installed.return_value = SimpleNamespace(version='4.2.0',metadata={'Requires-Python':'==3.11.*'},locate_file=lambda name:root/name)
            with self.assertRaisesRegex(RuntimeError,'Unknown bpy WHEEL'):
                unirig_blackwell.repair_bpy_metadata()
            self.assertEqual(wheel.read_bytes(),b'unrecognized metadata')

    def test_failed_runtime_replaces_stale_ready_and_preserves_other_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'UniRig').mkdir()
            (root / 'logs').mkdir()
            script = root / 'UniRig/check-runtime.py'
            shutil.copyfile(ROOT / 'UniRig/check-runtime.py', script)
            report = root / 'logs/components.json'
            report.write_text(json.dumps({'unirig': {'ready':True}, 'pixal3d': {'ready':True}}))
            with patch.dict(sys.modules, torch=Mock()), \
                 patch.object(gpu_probe, 'probe', side_effect=RuntimeError('CUDA kernel unavailable')):
                with self.assertRaises(SystemExit) as result:
                    runpy.run_path(str(script), run_name='__main__')
            self.assertEqual(result.exception.code, 1)
            value = json.loads(report.read_text(encoding='utf-8'))
            self.assertFalse(value['unirig']['ready'])
            self.assertIn('CUDA kernel unavailable', value['unirig']['message'])
            self.assertTrue(value['pixal3d']['ready'])
            self.assertEqual(list((root / 'logs').glob('*.tmp')), [])

    def test_detected_cuda_with_failed_kernel_is_rejected(self):
        torch = Mock()
        torch.cuda.is_available.return_value = True
        torch.cuda.get_device_name.return_value = 'Fixture GPU'
        torch.cuda.get_device_capability.return_value = (12, 0)
        torch.__version__ = '2.5.1+cu124'
        torch.version.cuda = '12.4'
        torch.inference_mode.return_value.__enter__ = Mock(side_effect=RuntimeError('no kernel image'))
        torch.inference_mode.return_value.__exit__ = Mock()
        with self.assertRaisesRegex(RuntimeError, 'sm_120.*no kernel image'):
            gpu_probe.check_torch(torch)

    def test_failed_extension_releases_cache_and_cannot_report_ready(self):
        torch = Mock()
        with patch.object(gpu_probe, 'check_torch', return_value={'gpu':'fixture'}), \
             patch.object(gpu_probe, 'check_extensions', side_effect=RuntimeError('spconv kernel failed')):
            with self.assertRaisesRegex(RuntimeError, 'spconv kernel failed'):
                gpu_probe.probe(torch)
        torch.cuda.empty_cache.assert_called_once()

    def test_blackwell_auto_selection_and_explicit_legacy(self):
        with patch.dict(os.environ, TRELLIS_UNIRIG_PROFILE='auto'), patch('subprocess.check_output', return_value='12.0\n'):
            self.assertEqual(unirig_blackwell.detect_profile(), 'blackwell')
        with patch.dict(os.environ, TRELLIS_UNIRIG_PROFILE='auto'), patch('subprocess.check_output', return_value='8.9\n'):
            self.assertEqual(unirig_blackwell.detect_profile(), 'legacy')
        with patch.dict(os.environ, TRELLIS_UNIRIG_PROFILE='auto'), patch('subprocess.check_output', return_value='12.1\n'):
            with self.assertRaisesRegex(RuntimeError, 'sm_120 only'):
                unirig_blackwell.detect_profile()
        with patch.dict(os.environ, TRELLIS_UNIRIG_PROFILE='legacy'), patch('subprocess.check_output') as command:
            self.assertEqual(unirig_blackwell.detect_profile(), 'legacy')
            command.assert_not_called()

    def test_blackwell_replaces_all_legacy_abi_dependencies(self):
        result = unirig_blackwell.common_requirements((ROOT / 'installer/requirements-unirig.txt').read_text())
        for value in ('cu124', 'pt25', 'flash-attn', 'nvidia-', 'spconv-cu120', 'cumm-cu120', 'sympy==', 'triton=='):
            self.assertNotIn(value, result)
        self.assertIn('numpy==1.26.4', result)
        self.assertIn('transformers==4.51.3', result)

    def test_spconv_metadata_patch_resumes_and_refuses_unknown_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            setup = root / 'setup.py'
            setup.write_text('a >=0.7.11, <0.8.0\nb >=0.7.11, <0.8.0\n')
            unirig_blackwell.patch_spconv_metadata(root)
            before = setup.read_bytes()
            unirig_blackwell.patch_spconv_metadata(root)
            self.assertEqual(before, setup.read_bytes())
            setup.write_text('unexpected')
            with self.assertRaisesRegex(RuntimeError, 'preserved'):
                unirig_blackwell.patch_spconv_metadata(root)
            self.assertEqual(setup.read_text(), 'unexpected')


if __name__ == '__main__':
    unittest.main()
