"""Exercise resource admission and converter recovery with small, valid fixtures."""
import base64
from io import BytesIO
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server_import_limits as limits
from server_conversion import supervise


def triangle(path):
    image = BytesIO()
    Image.new('RGB', (8, 8), 'red').save(image, format='PNG')
    vertices = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    document = dict(asset={'version': '2.0'}, scenes=[{'nodes': [0]}], nodes=[{'mesh': 0}],
                    meshes=[{'primitives': [{'attributes': {'POSITION': 0}}]}], buffers=[{'byteLength': len(vertices)}],
                    bufferViews=[{'buffer': 0, 'byteLength': len(vertices)}],
                    accessors=[{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3',
                                'min': [0, 0, 0], 'max': [1, 1, 0]}],
                    images=[{'uri': 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()}])
    encoded = json.dumps(document).encode()
    encoded += b' ' * (-len(encoded) % 4)
    path.write_bytes(struct.pack('<4s4I', b'glTF', 2, 28 + len(encoded) + len(vertices), len(encoded), 0x4e4f534a)
                     + encoded + struct.pack('<II', len(vertices), 0x004e4942) + vertices)


class ServerConversionTests(unittest.TestCase):
    def test_valid_asset_on_both_sides_of_budget(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'triangle.glb'
            triangle(path)
            self.assertEqual(limits.check_model(path)['accessors'][0]['count'], 3)
            for name, value in [('MAX_PIXELS', 63), ('MAX_VERTICES', 2), ('MAX_BYTES', path.stat().st_size - 1)]:
                with patch.object(limits, name, value), self.assertRaisesRegex(ValueError, 'budget'):
                    limits.check_model(path)
            self.assertEqual(limits.check_model(path)['images'][0]['uri'][:14], 'data:image/png')

    def test_timeout_then_normal_completion(self):
        with self.assertRaisesRegex(RuntimeError, 'time limit'):
            supervise([sys.executable, '-I', '-B', '-c', 'import time; time.sleep(5)'], 1)
        self.assertEqual(supervise([sys.executable, '-I', '-B', '-c', 'pass'], 10), 0)


if __name__ == '__main__':
    unittest.main()
