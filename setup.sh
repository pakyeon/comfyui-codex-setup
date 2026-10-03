#!/bin/sh
# Run with sh setup.sh; PYTHON can point to a ComfyUI environment's Python.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "${PYTHON:-python3}" "$script_dir/setup.py" "$@"
