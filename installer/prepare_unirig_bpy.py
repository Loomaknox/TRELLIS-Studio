"""Prepare the pinned Blender Python 3.11 wheel for the UniRig WSL profile.

The Linux wheel filename and Requires-Python field are correct. Its WHEEL
file came from the packaging interpreter and advertises the wrong ABI tag.
Only the verified upstream file is eligible for this metadata correction.
"""

import argparse
import base64
from copy import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


FILENAME = "bpy-4.2.0-cp311-cp311-manylinux_2_28_x86_64.whl"
SOURCE_URL = (
    "https://files.pythonhosted.org/packages/0b/bc/"
    "5245f98dafa39166a4d4701d64077d281a36110e780011de5c38135089aa/"
    + FILENAME
)
SOURCE_BYTES = 519384061
SOURCE_SHA256 = "a8217c2bd7b3424d1f51ce0698c0bf65439de352f7f6ed7b9942e2a9e5eb121b"
DIST_INFO = "bpy-4.2.0.dist-info"
WHEEL_NAME = f"{DIST_INFO}/WHEEL"
RECORD_NAME = f"{DIST_INFO}/RECORD"
OLD_TAG = b"Tag: cp39-cp39-manylinux_2_28_x86_64"
NEW_TAG = b"Tag: cp311-cp311-manylinux_2_28_x86_64"
BLOCK_BYTES = 8 * 1024**2


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def is_pinned_source(path):
    return (
        path.is_file()
        and path.stat().st_size == SOURCE_BYTES
        and sha256(path) == SOURCE_SHA256
    )


def download_source(target):
    if is_pinned_source(target):
        return
    if target.exists():
        raise ValueError(f"The cached bpy wheel has changed: {target}")
    part = target.with_suffix(".whl.part")
    if not is_pinned_source(part):
        print("Downloading the pinned Blender Python wheel.", file=sys.stderr, flush=True)
        subprocess.run(
            ["curl", "--fail", "--location", "--retry", "3", "--continue-at", "-",
             "--output", str(part), SOURCE_URL],
            check=True,
            stdout=sys.stderr,
        )
    if not is_pinned_source(part):
        raise ValueError(f"The downloaded bpy wheel failed SHA-256 verification: {part}")
    part.replace(target)


def replace_line(data, old, new):
    """Replace one complete line, preserving all other bytes and line endings."""
    lines = data.splitlines(keepends=True)
    indices = [index for index, line in enumerate(lines) if line.rstrip(b"\r\n") == old]
    if len(indices) != 1:
        raise ValueError("The pinned bpy wheel metadata has an unexpected format.")
    index = indices[0]
    lines[index] = new + lines[index][len(old):]
    return b"".join(lines)


def wheel_record(data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return WHEEL_NAME.encode("ascii") + b",sha256=" + digest + b"," + str(len(data)).encode("ascii")


def patch_wheel(source, destination):
    with zipfile.ZipFile(source) as original:
        old_wheel = original.read(WHEEL_NAME)
        new_wheel = replace_line(old_wheel, OLD_TAG, NEW_TAG)
        record = replace_line(original.read(RECORD_NAME), wheel_record(old_wheel), wheel_record(new_wheel))
        replacements = {WHEEL_NAME: new_wheel, RECORD_NAME: record}
        with zipfile.ZipFile(destination, "w") as corrected:
            corrected.comment = original.comment
            for member in original.infolist():
                info = copy(member)
                if member.filename in replacements:
                    corrected.writestr(info, replacements[member.filename])
                    continue
                with original.open(member) as incoming, corrected.open(
                    info, "w", force_zip64=member.file_size >= zipfile.ZIP64_LIMIT
                ) as outgoing:
                    shutil.copyfileobj(incoming, outgoing, BLOCK_BYTES)


def prepare(cache):
    source = cache / "upstream" / FILENAME
    target = cache / "corrected" / FILENAME
    receipt = target.with_suffix(".json")
    source.parent.mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    download_source(source)

    if receipt.is_file() and target.is_file():
        try:
            previous = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous = None
        if previous == {"source_sha256": SOURCE_SHA256, "wheel_sha256": sha256(target)}:
            return target

    print("Correcting the Python 3.11 ABI label in the verified bpy wheel.", file=sys.stderr, flush=True)
    with tempfile.TemporaryDirectory(prefix="bpy-wheel-", dir=target.parent) as directory:
        pending = Path(directory) / FILENAME
        patch_wheel(source, pending)
        data = {"source_sha256": SOURCE_SHA256, "wheel_sha256": sha256(pending)}
        pending_receipt = pending.with_suffix(".json")
        pending_receipt.write_text(json.dumps(data), encoding="utf-8")
        pending.replace(target)
        pending_receipt.replace(receipt)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache", type=Path)
    args = parser.parse_args()
    try:
        print(prepare(args.cache.resolve()), flush=True)
    except (KeyError, OSError, ValueError, subprocess.CalledProcessError, zipfile.BadZipFile) as error:
        print(f"UniRig bpy preparation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
