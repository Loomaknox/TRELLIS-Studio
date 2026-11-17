"""Run pinned upstream inference with its checkpoint metadata type allowed."""
from pathlib import Path
import runpy
import sys

from box import Box
from torch.serialization import safe_globals


if __name__ == '__main__':
    source = Path(__file__).resolve().parent / 'source'
    entry = source / 'run.py'
    sys.path.insert(0, str(source))
    sys.argv[0] = str(entry)
    # The pinned skin checkpoint contains python-box configuration metadata.
    # Keep weights-only loading; allow only this known type during inference.
    with safe_globals([Box]):
        runpy.run_path(str(entry), run_name='__main__')
