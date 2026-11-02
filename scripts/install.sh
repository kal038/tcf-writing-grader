#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -m venv "$project_dir/.venv"
"$project_dir/.venv/bin/python" -m pip install "$project_dir"
"$project_dir/.venv/bin/python" "$project_dir/scripts/install_unit.py" "$project_dir"
systemctl --user daemon-reload
printf '%s\n' 'Installed. Service has NOT been enabled or started.' 'Run tcf-importer setup using the project .venv/bin executable, then explicitly enable the service when ready.'
