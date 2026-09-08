#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo '请先安装 Python 3.10 或更新版本。'
  exit 1
fi
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else "需要 Python 3.10 或更新版本")'
if [ ! -x .venv/bin/python ]; then python3 -m venv .venv; fi
if ! .venv/bin/python -c 'import flask,requests,tos' >/dev/null 2>&1; then
  echo '正在准备首次运行环境…'
  .venv/bin/python -m pip install -r local-server/requirements.txt
fi
exec .venv/bin/python local-server/server.py
