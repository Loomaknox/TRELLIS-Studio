from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gpu_compat import configure_xformers


class AttentionCompatibility(unittest.TestCase):
    def test_blackwell_excludes_hopper_kernel(self):
        torch=SimpleNamespace(cuda=SimpleNamespace(get_device_capability=lambda:(12,0)))
        dispatch=SimpleNamespace(_set_use_fa3=Mock())
        with patch('gpu_compat.importlib.import_module',return_value=dispatch):
            self.assertIn('without Hopper',configure_xformers(torch))
        dispatch._set_use_fa3.assert_called_once_with(False)

    def test_ada_and_hopper_keep_default_dispatch(self):
        for capability in ((8,9),(9,0)):
            torch=SimpleNamespace(cuda=SimpleNamespace(get_device_capability=lambda:capability))
            with patch('gpu_compat.importlib.import_module') as imported:
                self.assertEqual(configure_xformers(torch),'xformers default dispatch')
                imported.assert_not_called()


if __name__=='__main__':unittest.main()
