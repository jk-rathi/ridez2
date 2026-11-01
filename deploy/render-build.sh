#!/bin/sh
# Native Render Python service; builds the website and installs backend packages.
set -eu
cd "$(dirname "$0")/.."
python -m pip install -r requirements.txt
if ! command -v npm >/dev/null 2>&1; then
    echo 'Node.js/npm is required to build the website. Set NODE_VERSION=22 in Render Environment.' >&2
    exit 1
fi
npm ci --include=dev --prefix frontend
npm run build --prefix frontend
python - <<'PY'
from pathlib import Path
import shutil
source = Path('frontend/dist')
target = Path('backend/frontend_dist')
if not (source / 'index.html').is_file():
    raise SystemExit('Frontend build did not produce index.html')
if target.exists():
    shutil.rmtree(target)
shutil.copytree(source, target)
PY
