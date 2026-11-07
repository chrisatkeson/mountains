#!/bin/sh
cd "$(dirname "$0")/.."
./scripts/download.sh data/tiles_gap.txt
echo "$(date +%H:%M) process_dem"; .venv/bin/python -I scripts/process_dem.py 2>&1 | grep -E "mosaic|elevation"
echo "$(date +%H:%M) build_tiles"; .venv/bin/python -I scripts/build_tiles.py 2>&1 | grep -E "complete"
echo "$(date +%H:%M) gap filled"
