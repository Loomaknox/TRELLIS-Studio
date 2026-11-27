"""Install the UltraTex operators and checkpoints used by Studio's native profiles."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from installer.native_workflow_install_common import (digest, fetch_asset, install_packages, safe_path,
                                                      verify_asset, write_json)
from installer.native_workflow_python import RUNTIME_PATH
from studio_model_assets import model_asset_path
from native_ultratex.dependencies import EXTRA, LEGACY, LOCK, dependency_paths, geometry_paths, missing_pins


RUNTIME = Path('runtime/native-game-texture')
MANIFEST = Path(__file__).with_name('native-ultratex-manifest.json')

TOKENIZER_NOTICE = (
    'Qwen2.5-VL-7B-Instruct tokenizer vocabulary and BPE merges, Apache-2.0.\n'
    'Source revision cc594898137f460bfe9f0759e9844b3ce807cfb5, https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct.\n'
    'This workflow variant adds the BPE version header and uses adapted token and template settings.\n'
    'It preserves Qwen3 think token IDs. The Qwen license text is included.\n'
)


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def _verify_license(root, data):
    terms = data['license']
    if digest(safe_path(root, terms['path'])) != terms['sha256']:
        raise ValueError('The bundled FLUX.2 license differs from the accepted version.')


def install_sources(root, data):
    def fetch_source(entry):
        return fetch_asset(root, entry, RUNTIME / entry['path'])

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch_source, data['source_files']))
    notice = safe_path(root, RUNTIME / 'tokenizer/NOTICE.txt')
    if not notice.exists():
        notice.write_text(TOKENIZER_NOTICE, encoding='utf-8')


def _source_receipt(data):
    return {'schema': 1, 'workflow': 'PixelArtistry Character 05 UltraTex', 'sources': data['source_revisions'],
            'files': {entry['path']: entry['sha256'] for entry in data['source_files']}}


def _model_receipt(data):
    return [{key: entry[key] for key in ('path', 'bytes', 'sha256')} for entry in data['models']]


def _install_dependencies(root):
    try:
        dependency_paths(root)
        return
    except RuntimeError:
        pass
    python = safe_path(root, RUNTIME_PATH)
    shared = geometry_paths(root)
    if shared:
        # Download only the pinned packages the shape component does not supply.
        runtime = safe_path(root, RUNTIME)
        runtime.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix='.ultratex-lock-', dir=runtime) as temporary:
            lock = Path(temporary) / LOCK.name
            lock.write_text('\n'.join(missing_pins(root, shared)) + '\n', encoding='utf-8')
            install_packages(root, python, EXTRA, lock)
    else:
        install_packages(root, python, LEGACY, root / LOCK)
    dependency_paths(root)


def _probe(root, receipt):
    python = safe_path(root, RUNTIME_PATH)
    runtime = safe_path(root, RUNTIME)
    program = '''
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
runtime = Path(sys.argv[2])
sys.path[:0] = [str(root / 'native_ultratex'), str(runtime / 'modules'), str(root)]
import prepare_character05
import gguf, moderngl, scipy.sparse, torch, triton
from transformers import Qwen2Tokenizer, Qwen3Config, Qwen3Model
from utx_graphics import bake, conditions, fastbake, guidance, render
from run_character05_texture import assert_native_imports, load_texture_recipe, selected_sources
from native_ultratex.dependencies import triton_compiler
triton_compiler()
selected_sources(json.loads(sys.argv[3]))
load_texture_recipe()
assert torch.cuda.is_available(), 'UltraTex requires CUDA.'
assert_native_imports()
print('Standalone UltraTex operators, recipe and CUDA verified.')
'''
    subprocess.run([python, '-I', '-B', '-c', program, root, runtime, json.dumps(receipt)], cwd=root, check=True)


def verify(root):
    data = manifest()
    _verify_license(root, data)
    for entry in data['source_files']:
        verify_asset(safe_path(root, RUNTIME / entry['path']), entry)
    for entry in data['models']:
        verify_asset(safe_path(root, model_asset_path(root, 'native-ultratex', entry['path'])), entry)
    dependency_paths(root)
    models = json.loads(safe_path(root, RUNTIME / 'model-manifest.json').read_text(encoding='utf-8'))
    if models != _model_receipt(data):
        raise ValueError('The installed UltraTex checkpoint manifest does not match the Setup version.')
    sources = json.loads(safe_path(root, RUNTIME / 'source-manifest.json').read_text(encoding='utf-8'))
    if sources != _source_receipt(data):
        raise ValueError('The installed UltraTex source manifest does not match the Setup version.')
    _probe(root, sources)


def setup_texture_only(root, *, verify_only=False, accept_license=False):
    """Complete texturing without installing the Game Asset mesh pipeline."""
    from installer import install_native_game_geometry as geometry
    from installer.native_workflow_python import install_runtime, verify_runtime
    from native_pixal3d import BIREFNET, _config, texture_mask_status
    from gpu_runtime import select_gpu

    if os.name != 'nt':
        raise RuntimeError('Native UltraTex Setup requires Windows x64.')
    if not verify_only and not accept_license:
        raise ValueError('Accept the FLUX.2 license before installing the UltraTex checkpoints.')
    select_gpu(root)
    if verify_only:
        verify_runtime(root)
        verify(root)
    else:
        _verify_license(root, manifest())
        python = install_runtime(root)
        geometry.install_reference_recipe(root)
        if not texture_mask_status()['available']:
            if (root / geometry.SHAPE_CONFIG).exists():
                raise ValueError('Repair the existing native BiRefNet configuration before installing UltraTex.')
            spec = geometry._manifest()
            geometry._install_wheels(root, python, spec)
            for entry in (*spec['vision_sources'], spec['birefnet_license']):
                fetch_asset(root, entry, entry['destination'])
            weight = next(entry for entry in spec['weights'] if entry['path'] == BIREFNET)
            path = fetch_asset(root, weight, model_asset_path(root, 'native-pixal3d', BIREFNET))
            shape = geometry._configurations()[geometry.SHAPE_CONFIG]
            write_json(root, 'config/native-ultratex-mask.json', {
                'python': shape['python'], 'birefnet': shape['birefnet'],
                'dependencies': [shape['dependencies'][0]],
                'weights': '../' + path.parents[1].relative_to(root).as_posix(),
            })
        install(root)
        verify(root)
    status = texture_mask_status()
    if not status['available']:
        raise ValueError(status['reason'])
    paths = _config('pixal3d', mask_only=True)
    spec = geometry._manifest()
    for entry in spec['vision_sources']:
        verify_asset(paths['birefnet'] / Path(entry['destination']).name, entry)
    weight = next(entry for entry in spec['weights'] if entry['path'] == BIREFNET)
    verify_asset(paths['weights'] / BIREFNET, weight)
    print('Standalone UltraTex and foreground mask verified.', flush=True)


def install(root):
    data = manifest()
    _verify_license(root, data)
    _install_dependencies(root)
    install_sources(root, data)
    receipt = _source_receipt(data)
    _probe(root, receipt)
    for entry in data['models']:
        fetch_asset(root, entry, model_asset_path(root, 'native-ultratex', entry['path']))
    write_json(root, RUNTIME / 'model-manifest.json', _model_receipt(data))
    write_json(root, RUNTIME / 'source-manifest.json', receipt)
