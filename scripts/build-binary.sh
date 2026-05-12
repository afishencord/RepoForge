#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install -r requirements-build.txt
python3 -m PyInstaller --clean --noconfirm packaging/repoforge.spec
