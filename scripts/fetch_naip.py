#!/usr/bin/env python
"""Fetch NAIP aerial imagery for the mosaic extent from the USGS National Map
ImageServer and assemble it into one texture aligned with viewer/data/meta.json.

The service returns at most 4000 px per side, so the extent is fetched as a grid
of tiles in EPSG:26913 and stitched. Output: viewer/data/naip.jpg
"""
import argparse, io, json, math, os, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
SERVICE = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage"
MAX_TILE = 2000   # the service allows 4000 but times out on big resamples


def fetch(bbox, size, sr, attempts=5):
    qs = urllib.parse.urlencode({
        "f": "image", "format": "jpg", "bbox": ",".join(f"{v:.3f}" for v in bbox),
        "bboxSR": sr, "imageSR": sr, "size": f"{size[0]},{size[1]}",
        "interpolation": "RSP_BilinearInterpolation", "noDataInterpretation": "esriNoDataMatchAny",
    })
    for i in range(attempts):
        try:
            with urllib.request.urlopen(f"{SERVICE}?{qs}", timeout=180) as r:
                data = r.read()
            img = Image.open(io.BytesIO(data)); img.load()
            return img.convert("RGB")
        except Exception as e:  # noqa: BLE001
            print(f"  retry {i + 1} for {bbox}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"failed to fetch {bbox}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--meta", default="viewer/data/meta.json")
    ap.add_argument("--out", default="viewer/data/naip.jpg")
    ap.add_argument("--width", type=int, default=16384, help="output width in pixels")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()

    meta = json.load(open(a.meta))
    b = meta["bounds"]; sr = meta["crs"].split(":")[1]
    ext_x, ext_y = b["right"] - b["left"], b["top"] - b["bottom"]
    W = a.width; H = int(round(W * ext_y / ext_x)); px = ext_x / W
    nx, ny = math.ceil(W / MAX_TILE), math.ceil(H / MAX_TILE)
    print(f"texture {W} x {H} @ {px:.2f} m/px, {nx * ny} tiles")

    jobs = []
    for j in range(ny):
        for i in range(nx):
            x0, x1 = i * MAX_TILE, min((i + 1) * MAX_TILE, W)
            y0, y1 = j * MAX_TILE, min((j + 1) * MAX_TILE, H)
            bbox = (b["left"] + x0 * px, b["top"] - y1 * px, b["left"] + x1 * px, b["top"] - y0 * px)
            jobs.append((x0, y0, bbox, (x1 - x0, y1 - y0)))

    out = Image.new("RGB", (W, H))
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for (x0, y0, bbox, size), img in zip(jobs, ex.map(lambda j: fetch(j[2], j[3], sr), jobs)):
            if img.size != size:
                img = img.resize(size, Image.LANCZOS)
            out.paste(img, (x0, y0))
            print(f"  tile at ({x0},{y0}) done, {time.time() - t0:.0f}s")
    out.save(a.out, quality=90, subsampling=0)
    out.resize((1400, 1400 * H // W)).save(os.path.splitext(a.out)[0] + "_preview.png")
    meta["naip"] = os.path.basename(a.out)
    meta["naip_credit"] = "USDA NAIP via USGS The National Map"
    json.dump(meta, open(a.meta, "w"), indent=2)
    print("wrote", a.out, f"{os.path.getsize(a.out) / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
