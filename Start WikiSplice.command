#!/bin/bash
# Double-click this file (macOS) to open WikiSplice.
# First run sets everything up automatically (takes a few minutes).
cd "$(dirname "$0")" || exit 1

# Check the environment's Python actually runs: it breaks when Homebrew upgrades
# Python and removes the old version, even though the file is still there.
if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
  if [ -d ".venv" ]; then
    echo "Python was updated since last time; rebuilding WikiSplice's Python environment..."
  else
    echo "First-time setup: creating a private Python environment..."
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "Python 3 isn't installed. Download it from https://www.python.org/downloads/"
    echo "then double-click this file again."
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi
  python3 -m venv --clear .venv || { read -n 1 -s -r -p "Setup failed. Press any key to close."; exit 1; }
  if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    rm -rf .venv && python3 -m venv .venv
  fi
  if ! .venv/bin/python -c "import sys" >/dev/null 2>&1; then
    read -n 1 -s -r -p "Couldn't set up Python. Press any key to close."
    exit 1
  fi
fi

# (Re)install packages if missing, or if requirements.txt changed (e.g. after an update)
REQ_HASH=$(shasum requirements.txt | cut -d" " -f1)
if ! .venv/bin/python -c "import playwright, requests" >/dev/null 2>&1 || [ "$(cat .venv/.requirements-hash 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "Installing required packages..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt || { read -n 1 -s -r -p "Install failed. Press any key to close."; exit 1; }
  echo "$REQ_HASH" > .venv/.requirements-hash
fi

# Downloads the screenshot browser the first time; instant afterwards.
.venv/bin/python -m playwright install chromium >/dev/null 2>&1 || .venv/bin/python -m playwright install chromium

.venv/bin/python app.py
