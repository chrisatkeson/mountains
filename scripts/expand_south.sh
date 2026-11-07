#!/bin/sh
# Wait for the south-block download to finish, then rebuild everything downstream.
cd "$(dirname "$0")/.."
while pgrep -f "download.sh data/tiles_south.txt" > /dev/null; do sleep 60; done
echo "$(date +%H:%M) download finished: $(ls data/raw/*.tif | wc -l | tr -d ' ') tiles"
grep -c FAILED data/download_south.log && echo "some tiles failed; rerun ./scripts/download.sh data/tiles_south.txt"
echo "$(date +%H:%M) process_dem"; .venv/bin/python -I scripts/process_dem.py 2>&1 | grep -vi warning
echo "$(date +%H:%M) build_tiles"; .venv/bin/python -I scripts/build_tiles.py 2>&1 | grep -E "^level|complete|mosaic"
echo "$(date +%H:%M) imagery"; .venv/bin/python -I scripts/fetch_naip_tiles.py --rebuild-levels --near 457000,4160000 2>&1 | grep -vE "tile at|retry"
echo "$(date +%H:%M) all done"
