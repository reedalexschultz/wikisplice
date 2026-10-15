#!/bin/bash
# Double-click this file (macOS) to open WikiSplice.
# First run sets everything up automatically (takes a few minutes).
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
  echo "First-time setup: creating a private Python environment..."
  if ! command -v python3 >/dev/null 2>&1; then
    echo ""
    echo "Python 3 isn't installed. Download it from https://www.python.org/downloads/"
    echo "then double-click this file again."
    read -n 1 -s -r -p "Press any key to close."
    exit 1
  fi
  python3 -m venv .venv || { read -n 1 -s -r -p "Setup failed. Press any key to close."; exit 1; }
fi

if ! .venv/bin/python -c "import playwright, requests" >/dev/null 2>&1; then
  echo "Installing required packages..."
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt || { read -n 1 -s -r -p "Install failed. Press any key to close."; exit 1; }
fi

# Downloads the screenshot browser the first time; instant afterwards.
.venv/bin/python -m playwright install chromium >/dev/null 2>&1 || .venv/bin/python -m playwright install chromium

.venv/bin/python app.py
