#!/usr/bin/env bash
set -euo pipefail

python -m pip install -r requirements.txt
exec uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
