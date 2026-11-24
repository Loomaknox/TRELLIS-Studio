"""Bound the resources represented by a standalone GLB before native conversion."""
import base64
from io import BytesIO
import math
import struct

from PIL import Image

from studio_import import validate_glb


MAX_BYTES = 500 * 1024**2
MAX_TRIANGLES = 5_000_000
MAX_VERTICES = 15_000_000
MAX_PIXELS = 128 * 1024**2
HEADER_BYTES = 1024**2


def _integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f'Invalid GLB {name}.')
    return value


def _uri_prefix(uri, offset, length):
    header, separator, data = uri.partition(',')
    if not separator or not header.startswith('data:') or not header.endswith(';base64'):
        raise ValueError('Server textures must use embedded binary or base64 data.')
    skip = offset % 3
    start = (offset // 3) * 4
    return base64.b64decode(data[start:start + ((skip + length + 2) // 3) * 4], validate=True)[skip:skip + length]


def _image_size(header):
    if header.startswith(b'\xabKTX 20\xbb\r\n\x1a\n') and len(header) >= 36:
        width, height, depth, layers, faces = struct.unpack_from('<5I', header, 20)
        if depth > 1 or layers > 1 or faces != 1:
            raise ValueError('Server imports require 2D material textures.')
        return width, height
    with Image.open(BytesIO(header)) as image:
        return image.size


def check_model(path):
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError('The model exceeds the Server import byte budget.')
    try:
        data = validate_glb(path)
        accessors = data['accessors']
        widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT2': 4, 'MAT3': 9, 'MAT4': 16}
        sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
        decoded = sum(_integer(a['count'], 'accessor count') * widths[a['type']] * sizes[a['componentType']]
                      for a in accessors)
        if decoded > 2 * 1024**3 or len(data.get('nodes', [])) > 100_000:
            raise ValueError('The model exceeds the Server decoded geometry budget.')
        def count(index):
            return _integer(accessors[_integer(index, 'accessor')]['count'], 'accessor count')
        geometry = []
        for mesh in data['meshes']:
            vertices = triangles = 0
            for primitive in mesh['primitives']:
                position = _integer(primitive['attributes']['POSITION'], 'position accessor')
                n = count(position)
                for field in ('min', 'max'):
                    if field in accessors[position]:
                        bounds = accessors[position][field]
                        if len(bounds) != 3 or not all(math.isfinite(value) for value in bounds):
                            raise ValueError('Invalid GLB position bounds.')
                indices = count(primitive['indices']) if 'indices' in primitive else n
                mode = primitive.get('mode', 4)
                vertices += n
                triangles += indices // 3 if mode == 4 else max(0, indices - 2) if mode in (5, 6) else 0
            geometry.append((vertices, triangles))
        instances = [0] * len(geometry)
        for node in data.get('nodes', []):
            if 'mesh' in node:
                attributes = node.get('extensions', {}).get('EXT_mesh_gpu_instancing', {}).get('attributes', {})
                instances[_integer(node['mesh'], 'mesh index')] += max((count(i) for i in attributes.values()), default=1)
        vertices = sum(max(1, n) * mesh[0] for n, mesh in zip(instances, geometry))
        triangles = sum(max(1, n) * mesh[1] for n, mesh in zip(instances, geometry))
        if vertices > MAX_VERTICES or triangles > MAX_TRIANGLES:
            raise ValueError('The model exceeds the Server geometry budget (5M triangles or 15M vertices).')
        textures = data.get('images', [])
        if len(textures) > 128:
            raise ValueError('The model exceeds the Server texture count budget (128 images).')
        with path.open('rb') as stream:
            stream.seek(12)
            json_size, = struct.unpack('<I', stream.read(4))
            stream.seek(20 + json_size)
            chunk = stream.read(8)
            binary_length, kind = struct.unpack('<II', chunk) if len(chunk) == 8 else (0, 0)
            binary_start = stream.tell()
            pixels = 0
            for image in textures:
                if 'uri' in image:
                    header = _uri_prefix(image['uri'], 0, HEADER_BYTES)
                else:
                    view = data['bufferViews'][_integer(image['bufferView'], 'image buffer view')]
                    offset = _integer(view.get('byteOffset', 0), 'image offset')
                    length = _integer(view['byteLength'], 'image length')
                    buffer = data['buffers'][_integer(view['buffer'], 'buffer index')]
                    if offset + length > _integer(buffer['byteLength'], 'buffer length'):
                        raise ValueError('A material image lies outside its GLB buffer.')
                    if 'uri' in buffer:
                        header = _uri_prefix(buffer['uri'], offset, min(length, HEADER_BYTES))
                    else:
                        if kind != 0x004e4942 or offset + length > min(binary_length, size - binary_start):
                            raise ValueError('Incomplete embedded GLB texture.')
                        stream.seek(binary_start + offset)
                        header = stream.read(min(length, HEADER_BYTES))
                width, height = _image_size(header)
                pixels += width * height
                if not 0 < min(width, height) or max(width, height) > 16384 or pixels > MAX_PIXELS:
                    raise ValueError('The model exceeds the Server texture dimension or total pixel budget.')
    except (KeyError, IndexError, TypeError, AttributeError, OverflowError, OSError, struct.error,
            Image.DecompressionBombError) as error:
        raise ValueError('Cannot verify the geometry or texture budget of this GLB.') from error
    return data
