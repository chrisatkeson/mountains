#!/usr/bin/env python
"""Fetch NAIP imagery as a tile pyramid aligned with the terrain tiles.

Imagery tile (L, tx, ty) covers exactly the same ground as terrain tile
(L, tx, ty) from build_tiles.py, at PX x PX pixels, so level 0 is 0.5 m/px.
Level 0 is fetched from the USGS National Map ImageServer in blocks of several
tiles per request (nearest the area of interest first, so the viewer becomes
useful early); coarser levels are 2x2 averages of the level below.

Output: viewer/data/imagery/<L>/<tx>_<ty>.jpg. Existing files are skipped, so
the script can be stopped and resumed.
"""
import argparse, io, json, math, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
SERVICE = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
PX = 1024          # pixels per tile side
BLOCK = 3          # tiles per request side (3 * 1024 = 3072 px, under the 4000 px service cap)


def fetch(bbox, size, sr, attempts=6):
    qs = urllib.parse.urlencode({
        "f": "image", "format": "jpg", "bbox": ",".join(f"{v:.3f}" for v in bbox),
        "bboxSR": sr, "imageSR": sr, "size": f"{size[0]},{size[1]}",
        "interpolation": "RSP_BilinearInterpolation", "noDataInterpretation": "esriNoDataMatchAny",
    })
    for i in range(attempts):
        try:
            with urllib.request.urlopen(f"{SERVICE}?{qs}", timeout=300) as r:
                data = r.read()
            img = Image.open(io.BytesIO(data)); img.load()
            return img.convert("RGB")
        except Exception as e:  # noqa: BLE001
            print(f"  retry {i + 1} for {[round(v) for v in bbox]}: {e}", file=sys.stderr, flush=True)
            time.sleep(5 * (i + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="viewer/data/tiles/index.json")
    ap.add_argument("--out", default="viewer/data/imagery")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--quality", type=int, default=85)
    ap.add_argument("--near", default="447500,4202500", help="E,N fetched first")
    ap.add_argument("--levels-only", action="store_true", help="skip fetching; just rebuild coarser levels")
    a = ap.parse_args()
    idx = json.load(open(a.index))
    b, sr, T = idx["bounds"], idx["crs"].split(":")[1], idx["tileSize"]
    levels = idx["levels"]
    nE, nN = map(float, a.near.split(","))

    def path(L, tx, ty):
        return os.path.join(a.out, str(L), f"{tx}_{ty}.jpg")

    lv0 = levels[0]
    if not a.levels_only:
        os.makedirs(os.path.join(a.out, "0"), exist_ok=True)
        blocks = []
        for by in range(0, lv0["ny"], BLOCK):
            for bx in range(0, lv0["nx"], BLOCK):
                tiles = [(tx, ty) for ty in range(by, min(by + BLOCK, lv0["ny"])) for tx in range(bx, min(bx + BLOCK, lv0["nx"]))]
                if all(os.path.exists(path(0, tx, ty)) for tx, ty in tiles):
                    continue
                cE = b["left"] + (bx + BLOCK / 2) * T; cN = b["top"] - (by + BLOCK / 2) * T
                blocks.append(((cE - nE) ** 2 + (cN - nN) ** 2, bx, by, tiles))
        blocks.sort()
        print(f"level 0: {len(blocks)} requests of {BLOCK}x{BLOCK} tiles @ {T / PX:.2f} m/px", flush=True)

        def do(block):
            _, bx, by, tiles = block
            w = max(tx for tx, _ in tiles) - bx + 1; h = max(ty for _, ty in tiles) - by + 1
            bbox = (b["left"] + bx * T, b["top"] - (by + h) * T, b["left"] + (bx + w) * T, b["top"] - by * T)
            img = fetch(bbox, (w * PX, h * PX), sr)
            if img is None:
                return f"FAILED block {bx},{by}"
            for tx, ty in tiles:
                x0, y0 = (tx - bx) * PX, (ty - by) * PX
                img.crop((x0, y0, x0 + PX, y0 + PX)).save(path(0, tx, ty), quality=a.quality)
            return None

        t0 = time.time(); done = 0
        with ThreadPoolExecutor(a.workers) as ex:
            for res in ex.map(do, blocks):
                done += 1
                if res: print(res, flush=True)
                if done % 25 == 0 or done == len(blocks):
                    el = time.time() - t0
                    print(f"  {done}/{len(blocks)} requests, {el / 60:.1f} min, ETA {el / done * (len(blocks) - done) / 60:.0f} min", flush=True)

    for L in range(1, len(levels)):
        lv, below = levels[L], levels[L - 1]
        os.makedirs(os.path.join(a.out, str(L)), exist_ok=True)
        t0 = time.time(); n = 0
        for ty in range(lv["ny"]):
            for tx in range(lv["nx"]):
                p = path(L, tx, ty)
                if os.path.exists(p):
                    continue
                canvas = Image.new("RGB", (2 * PX, 2 * PX), (40, 44, 52))
                found = False
                for dy in (0, 1):
                    for dx in (0, 1):
                        cp = path(L - 1, 2 * tx + dx, 2 * ty + dy)
                        if os.path.exists(cp):
                            canvas.paste(Image.open(cp), (dx * PX, dy * PX)); found = True
                if not found:
                    continue
                canvas.resize((PX, PX), Image.LANCZOS).save(p, quality=a.quality); n += 1
        print(f"level {L}: {n} tiles in {time.time() - t0:.0f}s", flush=True)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(a.out) for f in fs)
    print(f"imagery pyramid: {size / 1e9:.2f} GB in {a.out}")


if __name__ == "__main__":
    main()
