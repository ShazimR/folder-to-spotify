#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root regardless of the caller's directory.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m unittest discover -s tests -v
