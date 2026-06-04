#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="${LECTURE_DOWNLOADER_DIR:-/opt/lecture-downloader}"
SITE="$($PROJECT_DIR/.venv/bin/python - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
)"
export LD_LIBRARY_PATH="$SITE/nvidia/cublas/lib:$SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
exec "$PROJECT_DIR/.venv/bin/lecture-downloader" "$@"
