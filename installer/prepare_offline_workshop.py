"""Download and verify the pinned CPython 3.11 Windows Workshop and MCP media."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from installer.setup import fetch
from installer.native_workflow_install_common import safe_path


def prepare(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    spec = json.loads((ROOT / 'installer/locks/offline-workshop-win-cp311.json').read_text())
    foundation = json.loads((ROOT / 'installer/manifest.json').read_text())
    animations = [dict(item, path=Path(item['path']).name) for item in foundation['assets']
                  if item['group'] == 'animations']
    entries = [dict(foundation['sources']['uv'], path='uv.zip'), spec['python'], *spec['wheels'], *animations]
    def download(entry):
        destination = safe_path(directory, entry['path'])
        safe_path(directory, destination.with_name(destination.name + '.part'))
        fetch(entry, destination, root=directory)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, entries))
    print(f'Windows offline Workshop ready: {len(entries)} verified files.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    prepare(parser.parse_args().directory)
