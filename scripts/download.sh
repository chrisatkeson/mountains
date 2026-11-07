#!/bin/sh
# Download every tile in data/tiles.txt into data/raw, 8 at a time.
# Downloads go to a .part file and are renamed on success, so an existing .tif is always complete.
# Transfers that drop below 10 KB/s for 30 s are aborted and retried (e.g. after a network change).
cd "$(dirname "$0")/.." && mkdir -p data/raw
grep -v '^#' "${1:-data/tiles.txt}" | xargs -n 1 -P 8 sh -c '
  f=data/raw/$(basename "$0")
  [ -s "$f" ] && exit 0
  for attempt in 1 2 3 4 5; do
    curl -sS -L -C - --speed-time 30 --speed-limit 10000 -o "$f.part" "$0" && mv "$f.part" "$f" && exit 0
    sleep 5
  done
  echo "FAILED $0"'
echo "$(ls data/raw/*.tif | wc -l | tr -d ' ') tiles in data/raw"
