#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="$project_dir/backend/.venv"

if [[ ! -x "$venv_dir/bin/python" ]]; then
  "${PYTHON:-python3}" -m venv "$venv_dir"
fi

"$venv_dir/bin/python" -m pip install --disable-pip-version-check -q -r "$project_dir/backend/requirements.txt" pytest
(
  cd "$project_dir/backend"
  "$venv_dir/bin/python" -m pytest -q tests
)
(
  cd "$project_dir/frontend"
  npm install --no-package-lock --no-audit --no-fund
  npm run build
)
