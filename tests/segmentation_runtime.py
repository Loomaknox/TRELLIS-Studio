"""Regression checks for the isolated segmentation boundary and per-pipeline alpha rules."""
from pathlib import Path
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import native_high_detail
import reference_preparation as references
import segmentation_runtime as runtime


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        references._MASK_CACHE.clear()
        self.addCleanup(references._MASK_CACHE.clear)

    def test_existing_alpha_needs_no_environment_or_weights(self):
        source = Image.new('RGBA', (48, 48), (11, 12, 13, 127))
        with patch.dict(os.environ, TRELLIS_SEGMENTATION_PYTHON='missing'):
            cutouts = references._automatic_cutouts({'front': source}, Path('missing'), 128)
        self.assertEqual(cutouts['front'].tobytes(), source.tobytes())

    def test_masks_batch_views_cache_and_correct_alpha_modes(self):
        with TemporaryDirectory() as temp:
            weights = Path(temp) / 'model'
            weights.touch()
            image = Image.new('RGBA', (4, 8), (240, 120, 60, 255))
            sources = {'front': image, 'right': image.copy(), 'back': Image.new('RGBA', (4, 8), 'yellow')}
            with patch.object(references, 'masks', side_effect=lambda sources, _: [Image.new('L', im.size, 128) for im in sources]) as infer:
                composited = references._automatic_cutouts(sources, weights, 128)
                straight = references._automatic_cutouts(sources, weights, 128, straight_alpha=True)
            self.assertEqual([len(call.args[0]) for call in infer.call_args_list], [2, 0])
            self.assertEqual(composited['right'].getpixel((0, 0)), (120, 60, 30, 128))
            self.assertEqual(straight['front'].getpixel((0, 0)), (240, 120, 60, 128))

    def test_missing_runtime_suggests_repair_before_launch(self):
        with patch.dict(os.environ, TRELLIS_SEGMENTATION_PYTHON='missing'):
            with self.assertRaisesRegex(runtime.BackgroundRemovalError, 'Repair'):
                runtime.masks([Image.new('RGB', (16, 16))], Path('weights'))

    def test_timeout_releases_private_inputs(self):
        folders = []
        def timeout(command, **kwargs):
            self.assertEqual(command[1:3], ['-I', '-B'])
            folders.append(kwargs['cwd'])
            self.assertTrue((folders[-1] / '0.png').is_file())
            raise subprocess.TimeoutExpired(command, 1)
        with TemporaryDirectory() as temp:
            weights = Path(temp) / 'model'
            weights.touch()
            with patch.dict(os.environ, TRELLIS_SEGMENTATION_PYTHON=sys.executable), patch.object(subprocess, 'run', timeout):
                with self.assertRaisesRegex(runtime.BackgroundRemovalError, 'timed out'):
                    runtime.masks([Image.new('RGBA', (8, 8))], weights)
        self.assertFalse(folders[0].exists())

    def test_high_detail_preserves_existing_transparency(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'transparent.png'
            source = Image.new('RGBA', (32, 32))
            source.paste((240, 60, 120, 255), (4, 4, 28, 28))
            source.save(path)
            with patch.dict(os.environ, TRELLIS_SEGMENTATION_PYTHON='missing'):
                frame = native_high_detail._prepare_image(path, padding=2, remove_background=True, max_size=32)
        self.assertEqual(frame.mode, 'RGB')
        self.assertEqual(frame.getpixel((frame.width // 2, frame.height // 2)), (240, 60, 120))


if __name__ == '__main__':
    unittest.main()
