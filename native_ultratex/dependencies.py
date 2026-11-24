"""Find the pinned Python packages used by the native UltraTex worker."""

from importlib.metadata import distributions
import json
from pathlib import Path
import re


GEOMETRY = Path('runtime/native-pixal3d/packages')
LEGACY = Path('runtime/native-game-texture/deps')
EXTRA = Path('runtime/native-game-texture/extra-deps')
PYTHON_SITE = Path('.tools/wtivo/runtime/Lib/site-packages')
LOCK = Path('installer/requirements-native-ultratex.txt')


def geometry_paths(root):
    """Use the installed shape component's current package layout."""
    config = root / 'config/native-pixal3d.json'
    try:
        data = json.loads(config.read_text(encoding='utf-8-sig'))
        configured = {(config.parent / path).resolve() for path in data['dependencies']}
    except (OSError, TypeError, ValueError, KeyError):
        return ()
    merged = (root / GEOMETRY / 'studio-deps',)
    # The live split layout has a newer SciPy in deps. The shape worker also
    # gives support-deps priority, which is where the pinned SciPy lives.
    split = (root / GEOMETRY / 'support-deps', root / GEOMETRY / 'deps')
    for paths in (merged, split):
        if all(path in configured and path.is_dir() for path in paths):
            return paths
    return ()


def _normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def missing_pins(root, paths):
    """Check installed versions in the same precedence as the worker."""
    pins = []
    for line in (root / LOCK).read_text(encoding='utf-8').splitlines():
        if match := re.match(r'^([\w.-]+)==([^\s;]+)', line):
            pins.append((*match.groups(), line))
    if not pins:
        raise ValueError('The standalone UltraTex dependency lock has no pinned packages.')
    actual = {}
    for package in distributions(path=[str(path) for path in (*paths, root / PYTHON_SITE)]):
        name = package.metadata.get('Name')
        if name:
            actual.setdefault(_normalized(name), package.version)
    return [line for name, version, line in pins if actual.get(_normalized(name)) != version]


def dependency_paths(root):
    shared = geometry_paths(root)
    if shared:
        if not missing_pins(root, shared):
            return shared
        layered = (root / EXTRA, *shared)
        if layered[0].is_dir() and not missing_pins(root, layered):
            return layered
    legacy = (root / LEGACY,)
    if legacy[0].is_dir() and not missing_pins(root, legacy):
        return legacy
    raise RuntimeError('The standalone UltraTex Python dependencies are missing or differ from the pinned versions.')


def triton_compiler():
    import triton

    compiler = Path(triton.__file__).resolve().parent / 'runtime/tcc/tcc.exe'
    if not compiler.is_file():
        raise RuntimeError('The standalone UltraTex Triton compiler is missing.')
    return compiler
