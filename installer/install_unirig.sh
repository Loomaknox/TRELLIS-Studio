#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$STUDIO_ROOT/UniRig/runtime.sh"
# CUDA wheels routinely need more than the uv default download timeout.
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"
if [ "${1:-}" = --check-profile ]; then
    printf 'UniRig runtime profile: %s\n' "${UNIRIG_PROFILE:-legacy}"
    exit 0
fi
if [ -n "${UNIRIG_PROFILE:-}" ]; then
    printf 'Installing UniRig runtime profile: %s (CUDA compute %s)\n' "$UNIRIG_PROFILE" "$UNIRIG_COMPUTE_CAP"
fi
# Guided installs use the new pinned package profile. Keep the tested
# source-build fallback isolated for existing source installations.
PROFILE=""
if [ -z "${UNIRIG_PROFILE:-}" ]; then
    PROFILE="$(python3 "$STUDIO_ROOT/installer/unirig_blackwell.py" --detect)"
    if [ "$PROFILE" = blackwell ]; then
        python3 "$STUDIO_ROOT/installer/unirig_blackwell.py" --preflight
        if [ -z "${TRELLIS_UNIRIG_ENV:-}" ]; then export UNIRIG_ENV="$UNIRIG_BASE-blackwell"; fi
    else
        export UNIRIG_ENV="$UNIRIG_BASE"
    fi
    export PATH="$UNIRIG_ENV/venv/bin:$UNIRIG_ENV/tools:$PATH"
    export LD_LIBRARY_PATH="$UNIRIG_ENV/runtime/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
fi
mkdir -p "$UNIRIG_ENV/tools" "$UNIRIG_ENV/runtime/packages"
export UV_PYTHON_INSTALL_DIR="$UNIRIG_ENV/python"
export UV_CACHE_DIR="$UNIRIG_ENV/cache"
if [ ! -x "$UNIRIG_ENV/tools/uv" ]; then
    readarray -t PIN < <(python3 - "$STUDIO_ROOT/installer/manifest.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))['sources']['uv_linux'];print(p['url']);print(p['sha256'])
PY
)
    archive="$UNIRIG_ENV/tools/uv.tar.gz"
    curl -fL --retry 3 "${PIN[0]}" -o "$archive"
    printf '%s  %s\n' "${PIN[1]}" "$archive" | sha256sum --check -
    tar -xzf "$archive" --strip-components=1 -C "$UNIRIG_ENV/tools" uv-x86_64-unknown-linux-gnu/uv
fi
UV="$UNIRIG_ENV/tools/uv"
if [ ! -x "$UNIRIG_ENV/venv/bin/python" ]; then "$UV" venv --python "$UNIRIG_PYTHON_VERSION" "$UNIRIG_ENV/venv";fi
PY="$UNIRIG_ENV/venv/bin/python"
flags=(--extra-index-url "$UNIRIG_TORCH_INDEX" --find-links "$UNIRIG_PYG_WHEELS" --index-strategy unsafe-best-match)
if [ "$PROFILE" = blackwell ]; then
    "$PY" "$STUDIO_ROOT/installer/unirig_blackwell.py" --uv "$UV" --environment "$UNIRIG_ENV"
elif [ "${UNIRIG_PREBUILT_BLACKWELL:-0}" = 1 ]; then
    bpy_wheel="$(python3 "$STUDIO_ROOT/installer/prepare_unirig_bpy.py" "$UNIRIG_ENV/wheels")"
    # PyOpenGL 3.1.0 is a pure Python source distribution required by pyrender.
    compiled_packages=torch,torchvision,triton,cumm-cu128,spconv-cu128,flash-attn,torch-cluster,torch-scatter,open3d,bpy
    "$UV" pip install --python "$PY" --only-binary "$compiled_packages" -r "$UNIRIG_REQUIREMENTS" "$bpy_wheel" "${flags[@]}"
    "$UV" pip check --python "$PY"
else
    "$UV" pip install --python "$PY" -r "$UNIRIG_REQUIREMENTS" "${flags[@]}"
fi
# User-local runtime libraries: does not install a Linux NVIDIA driver or require sudo.
cd "$UNIRIG_ENV/runtime/packages"
apt-get download libsm6 libice6 libgomp1
for pkg in ./*.deb;do dpkg-deb -x "$pkg" "$UNIRIG_ENV/runtime";done
if [ "${1:-}" = --packages-only ]; then
    "$PY" "$STUDIO_ROOT/UniRig/check-runtime.py" --gpu-only
else
    "$PY" "$STUDIO_ROOT/UniRig/check-runtime.py"
fi
# Only a full successful validation activates the source-build runtime.
if [ "${1:-}" != --packages-only ] && [ -n "$PROFILE" ] && [ -z "${TRELLIS_UNIRIG_ENV:-}" ]; then
    if [ "$PROFILE" = blackwell ]; then
        mkdir -p "$UNIRIG_BASE"
        printf '%s\n' blackwell > "$UNIRIG_BASE/blackwell-ready.tmp"
        mv "$UNIRIG_BASE/blackwell-ready.tmp" "$UNIRIG_BASE/blackwell-ready"
    elif [ -f "$UNIRIG_BASE/blackwell-ready" ]; then
        rm -- "$UNIRIG_BASE/blackwell-ready"
    fi
fi
