"""Resolve the UniRig runtime for the Windows-selected GPU as seen by WSL."""
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit


def wsl_gpu_compute(gpu_uuid):
    direct = Path("/usr/lib/wsl/lib/nvidia-smi")
    executable = str(direct) if direct.is_file() else shutil.which("nvidia-smi")
    if not executable:
        raise ValueError("nvidia-smi is unavailable in WSL. Check the Windows NVIDIA driver and WSL2 GPU access.")
    try:
        probe = subprocess.run(
            [executable, "--query-gpu=uuid,compute_cap", "--format=csv,noheader,nounits"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("WSL could not enumerate NVIDIA GPUs. Check the Windows NVIDIA driver and WSL2 GPU access.") from error
    for row in csv.reader(probe.stdout.splitlines(), skipinitialspace=True):
        if len(row) == 2 and row[0].strip().casefold() == gpu_uuid.casefold():
            compute = row[1].strip()
            if re.fullmatch(r"\d+\.\d+", compute):
                return compute
            raise ValueError("CUDA compute capability is unavailable for the selected GPU in WSL.")
    raise ValueError("The selected Windows NVIDIA GPU is unavailable in WSL. Check GPU access and run Repair or resume components.")


def https_url(value):
    if not isinstance(value, str) or any(character.isspace() for character in value):
        raise ValueError("Invalid package index URL in the UniRig runtime profile.")
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname:
        raise ValueError("UniRig runtime package indexes must use HTTPS.")
    return value


def resolve(root):
    manifest = json.loads((root / "installer/gpu-runtime-profiles.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise ValueError("Unsupported GPU runtime manifest. Run the latest TRELLIS Studio Setup.")
    try:
        settings = json.loads((root / "config/runtime.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError("No NVIDIA GPU has been selected. Run Repair or resume components before starting UniRig.") from error
    gpu_uuid = settings.get("gpu_uuid")
    if not isinstance(gpu_uuid, str) or not re.fullmatch(r"GPU-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", gpu_uuid, re.IGNORECASE):
        raise ValueError("No valid NVIDIA GPU has been selected. Run Repair or resume components.")

    compute = wsl_gpu_compute(gpu_uuid)
    gpu = manifest["gpus"].get(compute, {})
    profile_id = gpu.get("unirig")
    if profile_id is None:
        raise ValueError(f"No packaged UniRig runtime for CUDA compute {compute}. You can use the other supported Studio engines.")
    if gpu["id"] != settings.get("gpu_profile"):
        raise ValueError("The GPU selected in Windows has a different WSL profile. Run Repair or resume components to refresh it.")
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", profile_id):
        raise ValueError("Invalid UniRig runtime profile identifier.")

    profile = manifest["unirig"][profile_id]
    requirements = (root / profile["requirements"]).resolve()
    if not requirements.is_relative_to((root / "installer").resolve()):
        raise ValueError("The UniRig runtime requirements must be inside the installer directory.")
    python_version = profile["python"]
    if not isinstance(python_version, str) or not re.fullmatch(r"3\.\d+(?:\.\d+)?", python_version):
        raise ValueError("Invalid Python version in the UniRig runtime profile.")
    index = https_url(profile["index_url"])
    find_links = https_url(profile["find_links"])
    fingerprint = hashlib.sha256(json.dumps(profile, sort_keys=True).encode())
    fingerprint.update(requirements.read_bytes())
    prebuilt_blackwell = profile.get("use_prebuilt_blackwell_wheels") is True
    if prebuilt_blackwell:
        fingerprint.update((root / "installer/prepare_unirig_bpy.py").read_bytes())
    return (gpu_uuid, compute, profile_id, fingerprint.hexdigest()[:16], str(requirements),
            python_version, index, find_links, int(prebuilt_blackwell))


if __name__ == "__main__":
    try:
        for field in resolve(Path(sys.argv[1]).resolve()):
            print(field)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"UniRig setup: {error}", file=sys.stderr)
        sys.exit(1)
