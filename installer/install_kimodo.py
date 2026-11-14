"""Install the optional pinned Kimodo CPU runtime without changing existing user data."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import queue
import subprocess
import sys
import threading
import time
import uuid

from kimodo_install_common import atomic_json, child, lock

ROOT = Path(__file__).resolve().parents[1]
MANAGED_BY = 'trellis-studio-kimodo-installer-v1'


def run_bridge(arguments, cancel_arguments):
    """Relay WSL output explicitly and keep interruption scoped to this installation."""
    process = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace', bufsize=1,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    messages = queue.Queue()
    def read_output():
        for line in process.stdout:
            messages.put(line)
        messages.put(None)
    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + 7200
    finished = False
    try:
        while not finished:
            if time.monotonic() > deadline:
                raise RuntimeError('Kimodo installation exceeded two hours; rerun to resume.')
            try:
                line = messages.get(timeout=1)
            except queue.Empty:
                continue
            if line is None:
                finished = True
            else:
                print(line.replace('\x00', '').rstrip('\r\n'), flush=True)
        return process.wait(timeout=10)
    finally:
        if process.poll() is None:
            try:
                subprocess.run(cancel_arguments, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        reader.join(timeout=2)
        process.stdout.close()
        process.stdin.close()


def linux_path(path):
    value = str(Path(path).resolve())
    if os.name == 'nt':
        match = re.fullmatch(r'([A-Za-z]):[\\/](.*)', value)
        if not match:
            raise ValueError('Kimodo installation requires a local drive path, not a network share.')
        return '/mnt/' + match[1].lower() + '/' + match[2].replace('\\', '/')
    return value


def installation_id(root):
    canonical = str(Path(root).resolve())
    if os.name == 'nt':
        canonical = canonical.casefold()
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


def existing_config(root):
    path = child(root, 'config/generated-animation-runtime.json')
    if not path.exists():
        return None
    if path.stat().st_size > 65536:
        raise RuntimeError('The existing runtime configuration was preserved; it exceeds the supported size.')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise RuntimeError('The existing runtime configuration was preserved; it is not a valid object.')
    return data


def activate(root, receipt, manifest, distribution, threads):
    """The config pointer is the commit: never expose an unverified engine."""
    if receipt.get('installation_id') != installation_id(root) or not receipt.get('smoke'):
        raise RuntimeError('The completed runtime did not provide the expected installation receipt.')
    config_path = child(root, 'config/generated-animation-runtime.json')
    previous = existing_config(root)
    if previous is not None and previous.get('managed_by') != MANAGED_BY:
        raise RuntimeError('A custom runtime configuration appeared during installation and was preserved.')
    skeleton_name = 'generated-animation-soma30-' + manifest['id'] + '.json'
    skeleton_path = child(root, 'config/' + skeleton_name)
    if skeleton_path.exists():
        if json.loads(skeleton_path.read_text()) != receipt['skeleton']:
            raise RuntimeError('An existing skeleton file was changed and was preserved.')
    else:
        atomic_json(skeleton_path, receipt['skeleton'])
    by_key = {entry['key']: entry for entry in manifest['artifacts']}
    config = dict(enabled=True, backend='wsl_cpu' if os.name == 'nt' else 'native_cpu',
                  executable=receipt['executable'], library_directory=receipt['library_directory'],
                  motion_model=receipt['motion_model'], text_model=receipt['text_model'], skeleton=str(skeleton_path),
                  model=manifest['model'], runtime=manifest['runtime'], source_revision=manifest['source_revision'],
                  model_sha256=by_key['motion']['sha256'], text_encoder_sha256=by_key['text']['sha256'],
                  threads=threads, steps=100, timeout_seconds=1200, managed_by=MANAGED_BY,
                  installation_id=receipt['installation_id'], manifest_id=manifest['id'])
    if distribution:
        config['distribution'] = distribution
    if previous:
        for name in ('enabled', 'threads', 'steps', 'timeout_seconds'):
            if name in previous:
                config[name] = previous[name]
    if previous == config:
        print('Runtime configuration is already current.', flush=True)
        return config
    if previous:
        backup = child(root, 'config/runtime-backups/generated-animation-' + uuid.uuid4().hex + '.json')
        atomic_json(backup, previous)
    atomic_json(config_path, config)
    return config


def install(root, distribution, accept, cache=None, threads=8):
    root = Path(root).resolve()
    if not root.is_dir() or not (root / 'app.py').is_file():
        raise ValueError('Select an existing TRELLIS Studio installation folder.')
    if not accept:
        raise ValueError('Read the NVIDIA and Meta model licenses, then pass --accept-model-licenses to continue.')
    if type(threads) is not int or not 1 <= threads <= 64:
        raise ValueError('CPU threads must be an integer between 1 and 64.')
    if os.name == 'nt' and (not distribution or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', distribution)):
        raise ValueError('Choose an existing initialized WSL2 distribution with --distribution.')
    if cache and not Path(cache).is_dir():
        raise ValueError('The optional reuse cache directory does not exist.')
    manifest_path = ROOT / 'installer/kimodo-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    with lock(child(root, 'config/.kimodo-install.lock')):
        previous = existing_config(root)
        if previous is not None and previous.get('managed_by') != MANAGED_BY:
            # Existing user-selected engines and disabled configurations are deliberate.
            if previous.get('enabled') is False:
                print('Existing disabled Kimodo configuration preserved. Generation remains disabled.', flush=True)
                return dict(status='preserved', configured=False)
            sys.path.insert(0, str(ROOT))
            from generated_animation_runtime import load_config
            try:
                load_config(root)
            except (OSError, ValueError, TypeError) as error:
                raise RuntimeError('Existing custom configuration is invalid and was preserved: ' + str(error)) from error
            print('Existing custom Kimodo configuration preserved. No runtime or settings were replaced.', flush=True)
            return dict(status='preserved', configured=previous.get('enabled') is True)
        config = child(root, 'config')
        token = uuid.uuid4().hex
        request_path = config / ('.kimodo-request-' + token + '.json')
        response_path = config / ('.kimodo-response-' + token + '.json')
        request = dict(installation_id=installation_id(root), manifest=linux_path(manifest_path),
                       threads=threads, accept_model_licenses=True, cache_dir=linux_path(cache) if cache else None, lifeline=True)
        atomic_json(request_path, request)
        helper = ROOT / 'installer/kimodo_install_linux.py'
        arguments = ['python3', linux_path(helper), '--request', linux_path(request_path), '--response', linux_path(response_path)]
        if os.name == 'nt':
            arguments = ['wsl.exe', '-d', distribution, '--', *arguments]
        else:
            arguments[0] = sys.executable
        try:
            code = run_bridge(arguments, arguments[:-2] + ['--cancel'])
            if code or not response_path.is_file():
                raise RuntimeError('Kimodo preparation did not finish. Existing settings are unchanged; rerun to resume.')
            receipt = json.loads(response_path.read_text())
            result = activate(root, receipt, manifest, distribution, threads)
            atomic_json(child(root, 'config/generated-animation-install.json'), receipt)
            print('Kimodo is installed and enabled. My animations can now generate humanoid motion.' if result['enabled']
                  else 'Kimodo is installed; the existing disabled setting was preserved.', flush=True)
            return result
        finally:
            request_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-root', type=Path, default=ROOT)
    parser.add_argument('--distribution')
    parser.add_argument('--accept-model-licenses', action='store_true')
    parser.add_argument('--cache-dir', type=Path, help='Optional existing artifact cache to reuse after hash verification.')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--plan', action='store_true', help='Describe pinned downloads and requirements without changing files.')
    args = parser.parse_args()
    if args.plan:
        manifest = json.loads((ROOT / 'installer/kimodo-manifest.json').read_text())
        print(json.dumps(dict(model=manifest['model'], backend='CPU', download_bytes=sum(e['bytes'] for e in manifest['artifacts']),
                             minimum_wsl_free_gib=12, requires='Initialized WSL2 x86_64, glibc >=2.35, Python >=3.10, AVX2/FMA/F16C',
                             installation_id=installation_id(args.install_root), license_urls=manifest['license_urls'],
                             existing_custom_config='preserved', automatic_system_changes=False), indent=2))
        return
    install(args.install_root, args.distribution, args.accept_model_licenses, args.cache_dir, args.threads)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Kimodo setup: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
