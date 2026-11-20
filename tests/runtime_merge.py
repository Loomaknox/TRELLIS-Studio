"""Regression checks for upstream guided setup plus existing source installs."""
from pathlib import Path
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'UniRig')]
import studio_import
import gpu_probe


class BlenderConfiguration(unittest.TestCase):
    def test_guided_selection_is_authoritative_before_drive_discovery(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'config').mkdir();exe=root/'blender.exe';exe.touch()
            (root/'config/runtime.json').write_text(json.dumps({'blender_path':str(exe)}),encoding='utf-8')
            with patch.object(studio_import,'__file__',str(root/'studio_import.py')),patch.dict(os.environ,TRELLIS_BLENDER=''),patch('shutil.which') as which:
                self.assertEqual(studio_import.find_blender(),exe)
                exe.unlink()
                self.assertIsNone(studio_import.find_blender())
                which.assert_not_called()


class RuntimeProbe(unittest.TestCase):
    def test_gpu_only_skips_models_but_full_probe_still_requires_them(self):
        spec=importlib.util.spec_from_file_location('merged_unirig_probe',ROOT/'UniRig/check-runtime.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        cuda=SimpleNamespace(is_available=lambda:True,get_device_capability=lambda:(12,0),get_device_name=lambda:'Fixture GPU')
        torch=SimpleNamespace(cuda=cuda,__version__='2.8.0+cu128')
        dependencies={name:Mock() for name in ('flash_attn','torch_scatter','torch_cluster','spconv','bpy','open3d')}
        with TemporaryDirectory() as directory,patch.dict(sys.modules,{'torch':torch,**dependencies}),patch.object(gpu_probe,'probe',return_value={'cuda':'12.8'}),patch.object(module,'verify_gpu'):
            result={}
            with patch.dict(os.environ,UNIRIG_COMPUTE_CAP='12.0',UNIRIG_PROFILE='fixture',UNIRIG_PREBUILT_BLACKWELL='0'):
                module.check_runtime(Path(directory),result,True)
                self.assertTrue(result['ready'])
                self.assertEqual(result['runtime_profile'],'fixture')
                with self.assertRaisesRegex(RuntimeError,'Missing model weights'):
                    module.check_runtime(Path(directory),{},False)


@unittest.skipUnless(sys.platform!='win32' and shutil.which('bash'),'Requires native Linux Bash')
class RuntimeSelection(unittest.TestCase):
    def fixture(self,root):
        (root/'UniRig').mkdir();(root/'installer').mkdir()
        shutil.copyfile(ROOT/'UniRig/runtime.sh',root/'UniRig/runtime.sh')
        shutil.copyfile(ROOT/'installer/install_unirig.sh',root/'installer/install_unirig.sh')
        base=root/'home/.local/share/trellis-unirig';base.mkdir(parents=True)
        (base/'blackwell-ready').write_text('blackwell\n')
        env={k:v for k,v in os.environ.items() if not k.startswith(('TRELLIS_UNIRIG_','UNIRIG_'))}
        env['HOME']=str(root/'home')
        return base,env

    def selection(self,root,env):
        script='source "$1"; printf "%s\\n" "$UNIRIG_ENV" "${UNIRIG_PROFILE:-}" "${UNIRIG_COMPUTE_CAP:-}"'
        return subprocess.check_output(['bash','-eu','-c',script,'fixture',str(root/'UniRig/runtime.sh')],env=env,text=True).splitlines()

    def test_source_marker_and_explicit_environment_are_preserved(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);base,env=self.fixture(root)
            self.assertEqual(self.selection(root,env)[0],str(base)+'-blackwell')
            env['TRELLIS_UNIRIG_ENV']=str(root/'explicit runtime')
            self.assertEqual(self.selection(root,env)[0],env['TRELLIS_UNIRIG_ENV'])

    def test_guided_profile_is_not_overwritten_by_source_marker(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);base,env=self.fixture(root);(root/'.trellis-guided-setup').touch()
            fields=['GPU-00000000-0000-0000-0000-000000000000','12.0','torch28-cu128-blackwell','fixturehash',str(root/'installer/requirements.txt'),'3.11','https://example.com/torch','https://example.com/pyg','1']
            (root/'UniRig/runtime-profile.py').write_text('print('+repr('\n'.join(fields))+')\n')
            selection=self.selection(root,env)
            self.assertIn('/trellis-unirig-guided-',selection[0])
            self.assertTrue(selection[0].endswith('/torch28-cu128-blackwell-fixturehash'))
            self.assertEqual(selection[1:],['torch28-cu128-blackwell','12.0'])
            result=subprocess.check_output(['bash',str(root/'installer/install_unirig.sh'),'--check-profile'],env=env,text=True)
            self.assertIn('torch28-cu128-blackwell',result)
            self.assertFalse(Path(selection[0]).exists())


if __name__=='__main__':unittest.main()
