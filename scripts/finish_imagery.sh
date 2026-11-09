#!/bin/sh
# Fetch remaining level-0 imagery tiles, then rebuild the coarse levels.
cd "$(dirname "$0")/.."
.venv/bin/python -I scripts/fetch_naip_tiles.py --workers 6 --near 457000,4160000 2>&1 | grep -vE "tile at"
.venv/bin/python -I scripts/fetch_naip_tiles.py --levels-only --rebuild-levels 2>&1 | grep -E "^level|pyramid"
echo "$(date +%H:%M) imagery complete"
