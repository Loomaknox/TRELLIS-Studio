"""Temporary workspace fixtures shared by public regression scripts."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import os


@contextmanager
def isolated_workspace(name):
    with TemporaryDirectory(prefix='trellis-test-' + name + '-') as directory:
        folder = Path(directory).resolve()
        values = {f'TRELLIS_{key}': str(folder / path) for key, path in (
            ('OUTPUT_DIR', 'outputs'), ('TRASH_DIR', 'trash'), ('STATE_DIR', 'state'),
            ('EXPORT_DIR', 'exports'), ('PROFILES_FILE', 'profiles.json'))}
        previous = {key: os.environ.get(key) for key in values}
        os.environ.update(values)
        try:
            yield folder
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
