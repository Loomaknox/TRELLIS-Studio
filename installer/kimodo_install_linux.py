"""User-scoped Linux build helper. Invoked through WSL without sudo or a shell command."""
from pathlib import Path
import argparse
import ast
import json
import math
import os
import platform
import re
import select
import signal
import shlex
import shutil
import struct
import subprocess
import sys
import time
import threading
import uuid

from kimodo_install_common import atomic_json, child, extract, fetch, lock, manifest_digest, sha256, verified


def probe():
    if sys.version_info < (3, 10):
        raise RuntimeError('The selected Linux distribution needs Python 3.10 or later.')
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('The Kimodo CPU runtime requires Linux x86_64.')
    libc, version = platform.libc_ver()
    if libc != 'glibc' or tuple(map(int, version.split('.')[:2])) < (2, 35):
        raise RuntimeError('The selected distribution needs glibc 2.35 or later (Ubuntu 22.04 or newer).')
    flags = set(re.search(r'^flags\s*:\s*(.+)$', Path('/proc/cpuinfo').read_text(), re.M).group(1).split())
    if not {'avx2', 'fma', 'f16c'} <= flags:
        raise RuntimeError('This CPU runtime requires AVX2, FMA and F16C instructions.')
    return dict(machine=platform.machine(), libc=version, python=platform.python_version(), home=str(Path.home()))


def run(arguments, folder, log_name, env=None, timeout=2400):
    log_path = child(folder, log_name)
    with log_path.open('w') as stream:
        process = subprocess.Popen(arguments, stdout=stream, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('The ' + log_name + ' stage exceeded its time limit. Private log: ' + str(log_path)) from error
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
    if code:
        raise RuntimeError('The ' + log_name + ' stage failed. Private log: ' + str(log_path))


def skeleton(source):
    values = {}
    for node in ast.parse((source / 'scripts/export_bvh.py').read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ('SOMA30_NAMES', 'SOMA30_PARENTS', 'SOMA30_OFFSETS'):
                values[name] = ast.literal_eval(node.value)
    if any(len(values.get(name, [])) != 30 for name in ('SOMA30_NAMES', 'SOMA30_PARENTS', 'SOMA30_OFFSETS')):
        raise RuntimeError('The pinned runtime did not contain its expected SOMA30 reference skeleton.')
    return dict(names=values['SOMA30_NAMES'], parents=values['SOMA30_PARENTS'], offsets=values['SOMA30_OFFSETS'],
                fps=30, units='metres', up='Y', forward='+Z', quaternion_order='xyzw')


def copy_verified(incoming, destination, entry):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if verified(destination, entry):
        return
    if destination.exists() or destination.is_symlink():
        raise RuntimeError('An existing runtime file was modified and was preserved: ' + destination.name)
    try:
        os.link(incoming, destination)
    except OSError:
        temporary = destination.with_name('.' + destination.name + '.partial-' + uuid.uuid4().hex)
        try:
            with incoming.open('rb') as source, temporary.open('xb') as stream:
                shutil.copyfileobj(source, stream, 8 * 1024**2)
            if not verified(temporary, entry):
                raise RuntimeError('A copied runtime file failed verification.')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def smoke(root, manifest, threads):
    directory = child(root, 'smoke')
    directory.mkdir(exist_ok=True)
    output = child(directory, 'motion-' + uuid.uuid4().hex)
    output.mkdir()
    prompt = child(directory, 'prompt.txt')
    prompt.write_text('A person stands still.', encoding='utf-8')
    env = dict(os.environ, LD_LIBRARY_PATH=str(root / 'lib'), KIMODO_BACKEND='cpu', KIMODO_THREADS=str(threads))
    run([str(root / 'bin/kmd-inspect'), str(root / 'weights/kimodo-soma-rp-v1.1-f32.gguf')], root, 'inspect.log', env, 120)
    run([str(root / 'bin/kmd-generate'), str(root / 'weights/kimodo-soma-rp-v1.1-f32.gguf'),
         str(root / 'weights/Llama-3-Kimodo-Q8_0.gguf'), str(prompt), '60', '10', '1234', str(output)],
        root, 'smoke.log', env, 900)
    positions = output / 'root_positions.f32'
    rotations = output / 'local_rotations_xyzw.f32'
    if positions.stat().st_size != 60 * 3 * 4 or rotations.stat().st_size != 60 * 30 * 4 * 4:
        raise RuntimeError('The runtime smoke test produced incomplete motion samples.')
    p = struct.unpack('<' + 'f' * (60 * 3), positions.read_bytes())
    q = struct.unpack('<' + 'f' * (60 * 30 * 4), rotations.read_bytes())
    if not all(math.isfinite(v) for v in p + q) or max(abs(v) for v in p) > 100:
        raise RuntimeError('The runtime smoke test produced invalid numeric values.')
    if any(abs(sum(v * v for v in q[i:i + 4]) - 1) > .005 for i in range(0, len(q), 4)):
        raise RuntimeError('The runtime smoke test produced invalid rotations.')
    return dict(frames=60, fps=30, steps=10, seed=1234, backend='CPU', purpose='installation validation only')


def runtime_paths(request, identifier, version):
    namespace = 'trellis-studio-setup-test' if request.get('test_install') is True else 'trellis-studio'
    home = Path.home()
    return child(home / '.local/share' / namespace / 'kimodo', identifier + '/' + version), child(home, '.cache/' + namespace + '/kimodo')


def install(request):
    system = probe()
    if request.get('accept_model_licenses') is not True:
        raise RuntimeError('Explicit acceptance of the model licenses is required.')
    identifier = request['installation_id']
    if not re.fullmatch('[a-f0-9]{20}', identifier):
        raise ValueError('Invalid installation identifier.')
    manifest_path = Path(request['manifest'])
    manifest = json.loads(manifest_path.read_text())
    if not re.fullmatch('[a-z0-9-]{1,80}', manifest['id']):
        raise ValueError('Invalid runtime version identifier.')
    root, cache = runtime_paths(request, identifier, manifest['id'])
    root.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    reuse = Path(request['cache_dir']).resolve() if request.get('cache_dir') else None
    by_key = {entry['key']: entry for entry in manifest['artifacts']}
    manifest_hash = manifest_digest(manifest)
    receipt_path = root / 'installation.json'
    with lock(root / '.install.lock'):
        owner = child(root, '.ownership.json')
        identity = dict(installation_id=identifier, manifest_sha256=manifest_hash)
        if owner.exists():
            if json.loads(owner.read_text()) != identity:
                raise RuntimeError('An unrelated runtime installation directory was preserved.')
        else:
            if any(path.name != '.install.lock' for path in root.iterdir()):
                raise RuntimeError('A nonempty unrecognized runtime directory was preserved.')
            atomic_json(owner, identity)
        atomic_json(child(root, '.installer-process.json'), dict(pid=os.getpid(), request=request.get('_request_path')))
        if receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text())
            if receipt.get('manifest_sha256') != manifest_hash:
                raise RuntimeError('The existing runtime version has different installation metadata and was preserved.')
            for name, digest in receipt['installed_files'].items():
                path = child(root, name)
                if not path.is_file() or sha256(path) != digest:
                    raise RuntimeError('An installed runtime file changed and was preserved: ' + name)
            print('Existing Kimodo installation verified; no rebuild or inference needed.', flush=True)
            return receipt
        if shutil.disk_usage(root).free < 12 * 1024**3:
            raise RuntimeError('Allow at least 12 GiB free in the selected WSL distribution before installation.')
        print('Preparing the portable CPU toolchain and pinned sources.', flush=True)
        for key in ('runtime', 'ggml', 'cmake', 'zig', 'ninja'):
            entry = by_key[key]
            extract(fetch(entry, cache, reuse), child(root, entry['target']), entry)
        tools = root / 'tools'
        child(root, 'build')
        child(root, 'zig-cache')
        child(root, 'zig-local-cache')
        ninja = tools / 'ninja/ninja'
        ninja.chmod(0o755)
        for name, compiler in (('cc', 'cc'), ('cxx', 'c++')):
            path = child(root, 'tools/zig-' + name)
            path.write_text('#!/bin/sh\nexec ' + shlex.quote(str(tools / 'zig/zig')) + ' ' + compiler
                            + ' -target x86_64-linux-gnu.2.35 "$@"\n')
            path.chmod(0o755)
        env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(root / 'zig-cache'), ZIG_LOCAL_CACHE_DIR=str(root / 'zig-local-cache'))
        cmake = str(tools / 'cmake/bin/cmake')
        print('Compiling the CPU runtime. This can take several minutes on the first installation.', flush=True)
        run([cmake, '-S', str(root / 'source/runtime'), '-B', str(root / 'build'), '-G', 'Ninja',
             '-DCMAKE_MAKE_PROGRAM=' + str(ninja), '-DCMAKE_C_COMPILER=' + str(tools / 'zig-cc'),
             '-DCMAKE_CXX_COMPILER=' + str(tools / 'zig-cxx'), '-DCMAKE_BUILD_TYPE=Release',
             '-DKIMODO_ENABLE_VULKAN=OFF', '-DKIMODO_BUILD_TESTS=OFF', '-DBUILD_TESTING=OFF', '-DGGML_OPENMP=OFF',
             '-DGGML_AVX=ON', '-DGGML_AVX2=ON', '-DGGML_F16C=ON', '-DGGML_FMA=ON',
             '-DKIMODO_GGML_SOURCE_DIR=' + str(root / 'source/ggml')], root, 'configure.log', env)
        run([cmake, '--build', str(root / 'build'), '--target', 'kmd-generate', 'kmd-inspect', '-j', '4'], root, 'build.log', env)
        binaries = [root / 'build/kmd-generate', root / 'build/kmd-inspect',
                    *sorted((root / 'build/ggml/src').glob('lib*.so*'))]
        installed = {}
        for incoming in binaries:
            if incoming.is_dir():
                continue
            name = ('lib/' if '.so' in incoming.name else 'bin/') + incoming.name
            entry = dict(bytes=incoming.stat().st_size, sha256=sha256(incoming))
            copy_verified(incoming.resolve(), child(root, name), entry)
            child(root, name).chmod(0o755)
            installed[name] = entry['sha256']
        print('Preparing verified motion weights, text encoder and license notices.', flush=True)
        for entry in manifest['artifacts']:
            if entry['kind'] != 'file':
                continue
            target = child(root, entry['target'])
            copy_verified(fetch(entry, cache, reuse), target, entry)
            installed[entry['target']] = entry['sha256']
        for name in ('runtime', 'ggml'):
            for notice in ('LICENSE', 'NOTICE'):
                license_source = root / 'source' / name / notice
                if not license_source.is_file():
                    continue
                target = child(root, 'licenses/' + name + '-' + notice)
                copy_verified(license_source, target, dict(bytes=license_source.stat().st_size, sha256=sha256(license_source)))
                installed['licenses/' + target.name] = sha256(target)
        canonical = skeleton(root / 'source/runtime')
        atomic_json(root / 'soma30.json', canonical)
        installed['soma30.json'] = sha256(root / 'soma30.json')
        print('Running a short CPU installation check before activating the runtime.', flush=True)
        validation = smoke(root, manifest, request['threads'])
        receipt = dict(schema=1, manifest_sha256=manifest_hash, installation_id=identifier, directory=str(root),
                       executable=str(root / 'bin/kmd-generate'), library_directory=str(root / 'lib'),
                       motion_model=str(root / 'weights/kimodo-soma-rp-v1.1-f32.gguf'),
                       text_model=str(root / 'weights/Llama-3-Kimodo-Q8_0.gguf'), skeleton=canonical,
                       installed_files=installed, smoke=validation, system=system)
        atomic_json(receipt_path, receipt)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--response', type=Path)
    parser.add_argument('--cancel', action='store_true')
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe()))
        return
    if not args.request or not args.response and not args.cancel:
        parser.error('--request and --response are required for installation')
    request = json.loads(args.request.read_text(encoding='utf-8-sig'))
    identifier = request.get('installation_id', '')
    version = json.loads(Path(request['manifest']).read_text()).get('id', '')
    if not re.fullmatch('[a-f0-9]{20}', identifier) or not re.fullmatch('[a-z0-9-]{1,80}', version):
        raise ValueError('Invalid installation identifier.')
    root, _ = runtime_paths(request, identifier, version)
    marker = child(root, '.installer-process.json')
    if args.cancel:
        if marker.is_file():
            info = json.loads(marker.read_text())
            pid = info.get('pid')
            if type(pid) is int and pid > 1:
                try:
                    command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                    if str(Path(__file__).resolve()).encode() in command and str(args.request.resolve()).encode() in command:
                        os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except FileNotFoundError:
                    pass
        return
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    lifeline_stop = threading.Event()
    lifeline = None
    if request.get('lifeline'):
        def parent_lifeline():
            # Only the controller owns the write end; closing Setup also closes it.
            while not lifeline_stop.is_set():
                if select.select([sys.stdin.fileno()], [], [], .25)[0]:
                    if not os.read(sys.stdin.fileno(), 1) and not lifeline_stop.is_set():
                        os.kill(os.getpid(), signal.SIGTERM)
                    return
        lifeline = threading.Thread(target=parent_lifeline, daemon=True)
        lifeline.start()
    request['_request_path'] = str(args.request.resolve())
    try:
        result = install(request)
        atomic_json(args.response, result)
        print('Kimodo runtime ready.', flush=True)
    finally:
        lifeline_stop.set()
        if lifeline:
            lifeline.join(timeout=1)
        if marker.is_file() and json.loads(marker.read_text()).get('pid') == os.getpid():
            marker.unlink()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Kimodo installation cancelled; completed cache files and existing configuration were preserved.', file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError) as error:
        print('Kimodo installation failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
