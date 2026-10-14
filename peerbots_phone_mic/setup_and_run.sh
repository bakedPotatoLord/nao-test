#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if ! command -v python3.11 >/dev/null 2>&1; then
  echo 'Python 3.11 is required. Attempting installation...'
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3.11 python3.11-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --needed python python-pip
  else
    echo 'Install Python 3.11+ and the venv module, then rerun.' >&2
    exit 1
  fi
fi
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON=python3.11
else
  PYTHON=python3
fi
"$PYTHON" setup.py
