"""Resolve identical pinned model weights to one ordinary file."""

from functools import lru_cache
import json
from pathlib import Path


# Native locations are the default for new downloads. The legacy locations
# remain readable for installations that already hold a verified weight there.
COMPONENTS = {
    'native-pixal3d': ('native-game-geometry-manifest.json', ('weights',), 'models/native-pixal3d'),
    'pixal3d': ('pixal3d-manifest.json', ('weights', 'single_image_weights'), 'models/pixal3d/models'),
    'native-ultratex': ('native-ultratex-manifest.json', ('models',), 'models/native-game-texture'),
    'ultratex': ('ultratex-manifest.json', ('assets',), 'models/ultratex'),
}
FAMILIES = {
    'native-pixal3d': ('native-pixal3d', 'pixal3d'),
    'pixal3d': ('native-pixal3d', 'pixal3d'),
    'native-ultratex': ('native-ultratex', 'ultratex'),
    'ultratex': ('native-ultratex', 'ultratex'),
}


@lru_cache(maxsize=32)
def _pinned_weights(root, component):
    name, groups, _directory = COMPONENTS[component]
    try:
        manifest = json.loads((root / 'installer' / name).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    return {entry['path']: (entry['bytes'], entry['sha256'])
            for group in groups for entry in manifest[group]}


def model_asset_path(studio_root, component, relative, *, directory=None):
    root = Path(studio_root).resolve()
    relative = Path(relative)
    if relative.anchor or '..' in relative.parts:
        raise ValueError('A model weight requires a path relative to its model directory.')
    own_directory = root / COMPONENTS[component][2]
    if directory is not None and Path(directory).resolve() != own_directory:
        return Path(directory) / relative
    canonical, legacy = FAMILIES[component]
    name = relative.as_posix()
    pin = _pinned_weights(root, canonical).get(name)
    if pin is None or pin != _pinned_weights(root, legacy).get(name):
        return own_directory / relative
    target = root / COMPONENTS[canonical][2] / relative
    existing_legacy = root / COMPONENTS[legacy][2] / relative
    if not target.exists() and existing_legacy.is_file():
        return existing_legacy
    return target
