"""GPU profile selection and a smoke test shared by setup and generation workers."""
import csv
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def load_profiles(root=ROOT):
    manifest = json.loads((root / 'installer' / 'gpu-runtime-profiles.json').read_text(encoding='utf-8-sig'))
    if manifest.get('schema') != 1:
        raise RuntimeError('Unsupported GPU package manifest. Reinstall TRELLIS Studio Setup.')
    return manifest


def guided_install(root=ROOT):
    return any((root / marker).is_file() for marker in ('.trellis-guided-setup', '.trellis-setup-test'))


def saved_gpu(root=ROOT):
    config = root / 'config' / 'runtime.json'
    if not guided_install(root) or not config.is_file():
        return {}
    settings = json.loads(config.read_text(encoding='utf-8-sig'))
    uuid = settings.get('gpu_uuid')
    if uuid and not re.fullmatch(r'GPU-[a-fA-F0-9-]{36}', uuid):
        raise RuntimeError('Invalid saved GPU identifier. Run Repair or resume components.')
    return settings


def select_gpu(root=ROOT):
    """Use the installer's GPU on every CUDA subprocess before importing Torch."""
    if uuid := saved_gpu(root).get('gpu_uuid'):
        os.environ['CUDA_VISIBLE_DEVICES'] = uuid


def windows_package_plan(capability, driver, root=ROOT):
    """Resolve the pinned Windows plan before downloading the engine or packages."""
    manifest = load_profiles(root)
    gpu = manifest['gpus'].get(capability, {})
    plan_id = gpu.get('windows')
    if not plan_id:
        raise RuntimeError(f'No Windows GPU package plan for CUDA capability {capability}. Workshop is available.')
    plan = manifest['windows'][plan_id]
    if not re.fullmatch(r'\d+\.\d+', driver) or tuple(map(int, driver.split('.'))) < tuple(map(int, plan['driver_min'].split('.'))):
        raise RuntimeError(f"Update the Windows NVIDIA driver to {plan['driver_min']} or newer for {plan_id}.")
    return gpu['id'], plan_id, plan


def detect_windows_package_plan(root=ROOT):
    settings = saved_gpu(root)
    uuid = settings.get('gpu_uuid')
    native_smi = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32' / 'nvidia-smi.exe'
    smi = str(native_smi) if native_smi.is_file() else shutil.which('nvidia-smi.exe')
    if not smi:
        raise RuntimeError('The NVIDIA driver utility (nvidia-smi) was not found.')
    command = [smi, '--query-gpu=uuid,driver_version,compute_cap', '--format=csv,noheader,nounits']
    if uuid:
        command.append(f'--id={uuid}')
    try:
        output = subprocess.check_output(command, text=True, timeout=8, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.SubprocessError as error:
        raise RuntimeError('The Windows NVIDIA driver could not query the selected GPU.') from error
    rows = [tuple(field.strip() for field in row) for row in csv.reader(output.splitlines()) if len(row) == 3]
    if not rows:
        raise RuntimeError('The selected NVIDIA GPU is unavailable. Run Setup again.')
    detected_uuid, driver, cc = rows[0]
    profile, plan_id, plan = windows_package_plan(cc, driver, root)
    if uuid and (detected_uuid.lower() != uuid.lower() or settings.get('gpu_profile') != profile):
        raise RuntimeError('The detected GPU no longer matches the saved profile. Run Repair or resume components.')
    return profile, plan_id, plan


def configure_attention(torch):
    if torch.cuda.is_available():
        capability = '.'.join(map(str, torch.cuda.get_device_capability()))
        profile = load_profiles()['gpus'].get(capability, {})
        if profile.get('disable_xformers_fa3') and importlib.metadata.version('xformers') == '0.0.32.post2':
            from xformers.ops.fmha.dispatch import _set_use_fa3
            _set_use_fa3(False)


def verify_installed_packages(torch):
    if not guided_install():
        return
    profile, plan_id, plan = detect_windows_package_plan()
    cc = '.'.join(map(str, torch.cuda.get_device_capability()))
    if load_profiles()['gpus'].get(cc, {}).get('id') != profile:
        raise RuntimeError(f'Torch initialized a GPU outside the selected {profile} profile.')
    for pin in plan['packages']:
        name, expected = pin.split('==', 1)
        actual = importlib.metadata.version(name)
        if actual != expected:
            raise RuntimeError(f'{plan_id} requires {pin}, but {name} {actual} is installed.')


def probe():
    select_gpu()
    engine = ROOT / 'engine'
    sys.path[:0] = [str(engine / 'o-voxel'), str(engine)]
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA is unavailable on the selected GPU.')
    verify_installed_packages(torch)
    configure_attention(torch)
    import cumesh
    from flex_gemm.ops.spconv import Algorithm, set_algorithm, sparse_submanifold_conv3d
    from o_voxel.serialize import decode_seq, encode_seq
    from xformers.ops import memory_efficient_attention
    from xformers.ops.fmha.attn_bias import BlockDiagonalMask

    with torch.inference_mode():
        device = 'cuda'
        values = torch.ones((32, 32), device=device)
        torch.testing.assert_close(values @ values, torch.full_like(values, 32))
        query = torch.ones((1, 16, 2, 64), dtype=torch.float16, device=device)
        mask = BlockDiagonalMask.from_seqlens([8, 8])
        torch.testing.assert_close(memory_efficient_attention(query, query, query, attn_bias=mask), query)

        points = torch.tensor([[0, 0, 0], [1, 0, 0], [0, 1, 0]], device=device)
        torch.testing.assert_close(decode_seq(encode_seq(points)), points.int())
        mesh = cumesh.CuMesh()
        faces = torch.tensor([[0, 1, 2]], dtype=torch.int32, device=device)
        mesh.init(points.float(), faces)
        mesh.compute_face_normals()
        torch.testing.assert_close(mesh.read_face_normals(), torch.tensor([[0., 0., 1.]], device=device))

        set_algorithm(Algorithm.EXPLICIT_GEMM)
        sparse_coords = torch.column_stack((torch.zeros_like(points[:, 0]), points)).int()
        features = torch.ones((3, 32), device=device, dtype=torch.float16)
        weights = torch.ones((32, 1, 1, 1, 32), device=device, dtype=torch.float16)
        result, _ = sparse_submanifold_conv3d(features, sparse_coords, torch.Size([1, 32, 2, 2, 2]), weights)
        torch.testing.assert_close(result, torch.full_like(features, 32))

    print(f'CUDA, xFormers, CuMesh, FlexGEMM and O-Voxel passed on {torch.cuda.get_device_name()}.')


if __name__ == '__main__':
    probe()
