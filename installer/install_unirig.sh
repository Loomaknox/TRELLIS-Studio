#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
source "$STUDIO_ROOT/UniRig/runtime.sh"
# Large CUDA wheels regularly exceed uv's 30-second default.
export UV_HTTP_TIMEOUT="${UV_HTTP_TIMEOUT:-300}"
PROFILE="$(python3 "$STUDIO_ROOT/installer/unirig_blackwell.py" --detect)"
if [ "$PROFILE" = blackwell ]; then
    # Fail before changing any environment when the compiler is unavailable.
    python3 "$STUDIO_ROOT/installer/unirig_blackwell.py" --preflight
    if [ -z "${TRELLIS_UNIRIG_ENV:-}" ]; then
        export UNIRIG_ENV="$UNIRIG_BASE-blackwell"
    fi
else
    export UNIRIG_ENV="$UNIRIG_BASE"
fi
export PATH="$UNIRIG_ENV/venv/bin:$UNIRIG_ENV/tools:$PATH"
export LD_LIBRARY_PATH="$UNIRIG_ENV/runtime/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
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
if [ ! -x "$UNIRIG_ENV/venv/bin/python" ]; then "$UV" venv --python 3.11 "$UNIRIG_ENV/venv";fi
PY="$UNIRIG_ENV/venv/bin/python"
if [ "$PROFILE" = blackwell ]; then
    "$PY" "$STUDIO_ROOT/installer/unirig_blackwell.py" --uv "$UV" --environment "$UNIRIG_ENV"
else
    "$UV" pip install --python "$PY" -r "$STUDIO_ROOT/installer/requirements-unirig.txt" \
    --extra-index-url https://download.pytorch.org/whl/cu124 \
    --find-links https://data.pyg.org/whl/torch-2.5.0+cu124.html --index-strategy unsafe-best-match
fi
# User-local runtime libraries: does not install a Linux NVIDIA driver or require sudo.
cd "$UNIRIG_ENV/runtime/packages"
apt-get download libsm6 libice6 libgomp1
for pkg in ./*.deb;do dpkg-deb -x "$pkg" "$UNIRIG_ENV/runtime";done
"$PY" "$STUDIO_ROOT/UniRig/check-runtime.py"
# Switch startup only after all CUDA operators, model files and config pass.
# Preserve the old venv so an interrupted build cannot damage it.
if [ -z "${TRELLIS_UNIRIG_ENV:-}" ]; then
    if [ "$PROFILE" = blackwell ]; then
        mkdir -p "$UNIRIG_BASE"
        printf '%s\n' blackwell > "$UNIRIG_BASE/blackwell-ready.tmp"
        mv "$UNIRIG_BASE/blackwell-ready.tmp" "$UNIRIG_BASE/blackwell-ready"
    elif [ -f "$UNIRIG_BASE/blackwell-ready" ]; then
        rm -- "$UNIRIG_BASE/blackwell-ready"
    fi
fi
