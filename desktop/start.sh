#!/usr/bin/env bash
set -euo pipefail

desktop_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_path="$desktop_directory/.venv/bin/python"

if [[ ! -x "$python_path" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
        printf '%s\n' \
            'Python 3.10 or newer is required. Install Python 3 and its venv module.' >&2
        exit 1
    fi

    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10 or newer is required.")'

    printf '%s\n' 'Creating the local Python environment...'
    python3 -m venv "$desktop_directory/.venv"
fi

printf '%s\n' 'Installing/checking dependencies in desktop/.venv...'
"$python_path" -m pip install \
    --disable-pip-version-check \
    -r "$desktop_directory/requirements.txt"

# Check actual APIs to detect incompatible packages.
if ! (
    cd -- "$desktop_directory"
    "$python_path" - <<'PY'
from panel_studio.firmware_cli import validate_build_dependencies
from panel_studio.firmware_core import WorkflowError

try:
    validate_build_dependencies()
except WorkflowError as error:
    raise SystemExit(str(error))
PY
); then
    printf '%s\n' \
        'Dependency check failed. See the installation instructions in README.md.' >&2
    exit 1
fi

if [[ "${1:-}" == '--install-only' ]]; then
    exit 0
fi

exec "$python_path" "$desktop_directory/run.py" "$@"
