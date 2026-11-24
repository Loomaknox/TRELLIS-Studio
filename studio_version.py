"""Application version shared by Studio, its local API and MCP bridge."""
import json
from pathlib import Path
import re
import subprocess

VERSION = json.loads(Path(__file__).with_name('package.json').read_text(encoding='utf-8'))['version']


def build_identity(root=Path(__file__).resolve().parent):
    """Report packaged identities without treating a legacy payload hash as a Git commit."""
    root = Path(root)
    receipt = root / 'bundled-web.json'
    release = {}
    commit = None
    if receipt.is_file():
        release = json.loads(receipt.read_text(encoding='utf-8-sig'))
        commit = release.get('fork_commit')
    elif (root / '.git').exists():
        try:
            commit = subprocess.check_output(
                ['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'], text=True,
                stderr=subprocess.DEVNULL, timeout=3, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            ).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    token = release.get('source_revision')
    return {'upstream_version': VERSION, 'fork_commit': commit if re.fullmatch('[0-9a-f]{40}', str(commit)) else None,
            'package_source_modified': release.get('source_modified') if type(release.get('source_modified')) is bool else None,
            'package_payload_sha256': token if re.fullmatch('[0-9a-f]{64}', str(token)) else None}
