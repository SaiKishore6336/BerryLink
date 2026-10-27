#!/usr/bin/env bash
# Start the BerryLink desktop gateway. Extra arguments go to berrylink.app.
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${PYTHON:-}" ]]; then
    PY="$PYTHON"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY="$ROOT/.venv/bin/python"
else
    PY="$(command -v python3 || true)"
fi

if [[ -z "$PY" || ! -x "$PY" ]]; then
    echo "Python 3 was not found. Create .venv and install desktop/requirements.txt first." >&2
    exit 1
fi

export PYTHONPATH="$ROOT/desktop${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m berrylink.app "$@"
