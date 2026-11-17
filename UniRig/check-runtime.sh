#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/runtime.sh"
require_unirig_python
exec "$UNIRIG_PYTHON" "$UNIRIG_ROOT/check-runtime.py"
