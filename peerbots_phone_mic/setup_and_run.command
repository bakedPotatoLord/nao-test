#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v python3.11 >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    echo 'Installing Homebrew (may require administrator permission)...'
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
  fi
  brew install python@3.11
fi
python3.11 setup.py
