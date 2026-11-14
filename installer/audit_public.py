"""Reject private runtime data and obvious credentials from source/payload inventories."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess

PRIVATE_ROOTS = {'config', 'state', 'generated-animations', 'server-data', 'outputs', 'trash', 'exports', 'models', 'engine',
                 '.git', '.venv', '.mcp-venv', '.downloads', 'logs', 'qa', 'temp'}
SECRETS = (
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    re.compile(r'(?i)[A-Z]:[/\\]Users[/\\](?!Public(?:[/\\]|$)|Default(?:[/\\]|$)|<)[^/\\\s"\']+'),
)


def audit(root, paths, deny_literals=()):
    errors = []
    for name in paths:
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                or not path.parts or path.parts[0].lower() in PRIVATE_ROOTS
                or path.suffix.lower() in {'.sqlite', '.sqlite3', '.db', '.pem', '.key', '.log', '.pfx', '.p12', '.crt', '.cer', '.jks'}
                or path.name in {'AGENTS.md', 'LOCAL_PRODUCT_BACKLOG.md'}):
            errors.append((name, 'private or unsafe path'))
            continue
        file = root.joinpath(*path.parts)
        resolved = file.resolve()
        if (file.is_symlink() or not resolved.is_relative_to(root.resolve()) or not file.is_file()
                or resolved.relative_to(root.resolve()).parts[0].lower() in PRIVATE_ROOTS
                or any(parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction())
                       for parent in file.parents if parent != root and root in parent.parents)):
            errors.append((name, 'not a regular payload file'))
            continue
        content = file.read_bytes()
        for literal in deny_literals:
            if literal and (literal.encode('utf-8') in content or literal.encode('utf-16-le') in content):
                errors.append((name, 'private literal found'))
        # Binary third-party executables and images are inventoried by hash, not text-scanned.
        if b'\0' in content[:8192]:
            continue
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            continue
        if any(pattern.search(text) for pattern in SECRETS):
            errors.append((name, 'credential or personal home path'))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--paths-file', type=Path, help='UTF-8 relative paths, one per line')
    parser.add_argument('--deny-literal', action='append', default=[], help='Private audit input, never saved to the release')
    args = parser.parse_args()
    paths = (args.paths_file.read_text(encoding='utf-8-sig').splitlines() if args.paths_file
             else subprocess.check_output(['git', '-C', str(args.root), '-c', 'core.quotePath=false',
                                           'ls-files', '--cached', '--others', '--exclude-standard'], text=True).splitlines())
    errors = audit(args.root, paths, args.deny_literal)
    for name, reason in errors:
        print(f'{name}: {reason}')
    if errors:
        raise SystemExit('Public inventory audit failed.')
    print(f'Public inventory audit passed: {len(paths)} files. Review diffs and binary provenance before publication.')


if __name__ == '__main__':
    main()
