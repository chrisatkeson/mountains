#!/bin/sh
# Download point cloud tiles listed in data/lpc_crestone.txt into data/lpc.
# rockyweb.usgs.gov throttles hard (HTTP 429), so: one connection, resume partial
# files, and back off from 1 to 10 minutes between failures. Skips complete files.
cd "$(dirname "$0")/.." && mkdir -p data/lpc
list="${1:-data/lpc_crestone.txt}"
while read -r url; do
  f=data/lpc/$(basename "$url")
  [ -s "$f" ] && continue
  wait=60
  while :; do
    code=$(curl -s -S -f -C - -o "$f.part" -w '%{http_code}' "$url")   # -f: never write an error page into the partial file
    if [ "$code" = "200" ] || [ "$code" = "206" ]; then mv "$f.part" "$f"; echo "$(date +%H:%M:%S) ok $(basename "$f") $(du -k "$f" | cut -f1)K"; break; fi
    echo "$(date +%H:%M:%S) http $code for $(basename "$f"); waiting ${wait}s"
    [ "$code" = "416" ] && { mv "$f.part" "$f"; break; }   # range already complete
    sleep $wait; [ $wait -lt 600 ] && wait=$((wait * 2))
  done
done < "$list"
echo "$(date +%H:%M:%S) done: $(ls data/lpc/*.laz 2>/dev/null | wc -l | tr -d ' ') laz files"
