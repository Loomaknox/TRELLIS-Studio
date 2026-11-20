#!/usr/bin/env bash
export UNIRIG_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
_studio_root="$(dirname -- "$UNIRIG_ROOT")"
if [ -f "$_studio_root/.trellis-guided-setup" ] || [ -f "$_studio_root/.trellis-setup-test" ]; then
    _studio_selection="$(python3 "$UNIRIG_ROOT/runtime-profile.py" "$_studio_root")" || return 1
    mapfile -t _studio_profile <<< "$_studio_selection"
    _studio_id="$(printf '%s' "$UNIRIG_ROOT" | sha256sum | cut -c1-16)"
    export CUDA_VISIBLE_DEVICES="${_studio_profile[0]}"
    export UNIRIG_COMPUTE_CAP="${_studio_profile[1]}"
    export UNIRIG_PROFILE="${_studio_profile[2]}"
    _studio_scope=trellis-unirig-guided
    if [ -f "$_studio_root/.trellis-setup-test" ]; then _studio_scope=trellis-unirig-setup-test; fi
    export UNIRIG_ENV="$HOME/.local/share/$_studio_scope-$_studio_id/$UNIRIG_PROFILE-${_studio_profile[3]}"
    unset _studio_scope
    UNIRIG_REQUIREMENTS="${_studio_profile[4]}"
    UNIRIG_PYTHON_VERSION="${_studio_profile[5]}"
    UNIRIG_TORCH_INDEX="${_studio_profile[6]}"
    UNIRIG_PYG_WHEELS="${_studio_profile[7]}"
    export UNIRIG_PREBUILT_BLACKWELL="${_studio_profile[8]}"
    UNIRIG_PYTHON="$UNIRIG_ENV/venv/bin/python"
    unset _studio_id _studio_selection _studio_profile
else
    _studio_unirig="$HOME/.local/share/trellis-unirig"
    if [ -f "$_studio_root/bundled-web.json" ]; then
        _studio_unirig="$HOME/.local/share/trellis-unirig-setup"
    fi
    export UNIRIG_BASE="${TRELLIS_UNIRIG_ENV:-$_studio_unirig}"
    export UNIRIG_ENV="$UNIRIG_BASE"
    if [ -z "${TRELLIS_UNIRIG_ENV:-}" ] && [ -f "$UNIRIG_BASE/blackwell-ready" ]; then
        export UNIRIG_ENV="$UNIRIG_BASE-blackwell"
    fi
    unset UNIRIG_PROFILE UNIRIG_COMPUTE_CAP
    UNIRIG_REQUIREMENTS="$_studio_root/installer/requirements-unirig.txt"
    UNIRIG_PYTHON_VERSION="3.11"
    UNIRIG_TORCH_INDEX="https://download.pytorch.org/whl/cu124"
    UNIRIG_PYG_WHEELS="https://data.pyg.org/whl/torch-2.5.0+cu124.html"
    UNIRIG_PYTHON="python"
    unset UNIRIG_PREBUILT_BLACKWELL
    unset _studio_unirig
fi
unset _studio_root
export PATH="$UNIRIG_ENV/venv/bin:$UNIRIG_ENV/tools:$PATH"
export LD_LIBRARY_PATH="$UNIRIG_ENV/runtime/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}"
if [ "${UNIRIG_PREBUILT_BLACKWELL:-0}" = 1 ]; then
    # The paired wheels link to CUDA libraries installed by the pinned Linux Torch stack.
    _studio_nvidia="$UNIRIG_ENV/venv/lib/python$UNIRIG_PYTHON_VERSION/site-packages/nvidia"
    export LD_LIBRARY_PATH="$_studio_nvidia/cuda_runtime/lib:$_studio_nvidia/cuda_nvrtc/lib:$LD_LIBRARY_PATH"
    unset _studio_nvidia
fi
export HF_HOME="$UNIRIG_ROOT/models/huggingface"
export WANDB_MODE=disabled
export HF_HUB_DISABLE_TELEMETRY=1
export PYTHONUNBUFFERED=1

require_unirig_python() {
    if [ "$UNIRIG_PYTHON" != python ] && [ ! -x "$UNIRIG_PYTHON" ]; then
        printf 'The selected UniRig runtime is missing. Run Repair or resume components.\n' >&2
        return 1
    fi
}
