#!/usr/bin/env python
"""Mosaic USGS 1 m DEM tiles, downsample, and emit assets for the web viewer.

Outputs (into viewer/data/):
  heightmap.bin   Uint16 little-endian grid, row-major, north row first. 0 = nodata.
  texture.jpg     hillshade blended with hypsometric tint
  hillshade.jpg   greyscale hillshade only
  meta.json       grid size, bounds, elevation range, CRS
  preview.png     quick-look image for sanity checking

Tiles from several lidar projects may cover the same 10 km cell; the mosaic takes
the first valid value in PROJECT_PRIORITY order, so later projects only fill gaps.
"""
import argparse, glob, json, math, os, sys, time
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.io import MemoryFile
from PIL import Image

PROJECT_PRIORITY = ["CO_SanLuisJuanMiguel_2020", "CO_ParkFremontCuster_2018",
                    "CO_EasternColorado_2018", "UT_COUTAML"]


def priority(path):
    name = os.path.basename(path)
    for i, p in enumerate(PROJECT_PRIORITY):
        if p in name:
            return (i, name)
    return (len(PROJECT_PRIORITY), name)


def hillshade(z, cellsize, az_deg=315.0, alt_deg=45.0, zfactor=1.0):
    az = math.radians(360.0 - az_deg + 90.0)
    alt = math.radians(alt_deg)
    gy, gx = np.gradient(z * zfactor, cellsize)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    shaded = (np.sin(alt) * np.cos(slope)
              + np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(shaded, 0, 1)


def hypsometric(z, zmin, zmax):
    """Terrain colour ramp: green lowlands -> tan -> brown -> white peaks."""
    stops = np.array([
        [0.00,  60, 110,  60],
        [0.25, 130, 160,  90],
        [0.50, 190, 170, 110],
        [0.75, 150, 110,  80],
        [0.92, 230, 230, 230],
        [1.00, 255, 255, 255],
    ], dtype=np.float32)
    t = np.clip((z - zmin) / max(zmax - zmin, 1e-6), 0, 1)
    rgb = np.empty(z.shape + (3,), dtype=np.float32)
    for c in range(3):
        rgb[..., c] = np.interp(t, stops[:, 0], stops[:, c + 1])
    return rgb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="viewer/data")
    ap.add_argument("--height-size", type=int, default=8192, help="pixels across the long axis of the heightmap")
    ap.add_argument("--texture-size", type=int, default=8192, help="pixels across the long axis of the texture")
    ap.add_argument("--name", default="Sangre de Cristo / Wet Mountain Valley, CO")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    tifs = sorted(glob.glob(os.path.join(a.raw, "*.tif")), key=priority)
    if not tifs:
        sys.exit(f"no .tif files in {a.raw}")
    print(f"{len(tifs)} tiles")

    srcs = [rasterio.open(p) for p in tifs]
    crs = srcs[0].crs
    bad = [s.name for s in srcs if s.crs != crs or abs(s.res[0] - srcs[0].res[0]) > 1e-6]
    if bad:
        sys.exit(f"tiles with mismatched CRS/resolution: {bad}")
    left = min(s.bounds.left for s in srcs); right = max(s.bounds.right for s in srcs)
    bottom = min(s.bounds.bottom for s in srcs); top = max(s.bounds.top for s in srcs)
    res = srcs[0].res[0]
    native_w = int(round((right - left) / res)); native_h = int(round((top - bottom) / res))
    print(f"mosaic native size {native_w} x {native_h} @ {res} m, CRS {crs}")

    def mosaic_at(size):
        t0 = time.time()
        scale = size / max(native_w, native_h)
        mems = []
        for s in srcs:
            ow = max(1, int(round(s.width * scale))); oh = max(1, int(round(s.height * scale)))
            arr = s.read(1, out_shape=(oh, ow), resampling=Resampling.average, masked=True).filled(np.nan)
            tr = s.transform * s.transform.scale(s.width / ow, s.height / oh)
            mf = MemoryFile()
            ds = mf.open(driver="GTiff", height=oh, width=ow, count=1, dtype="float32",
                         crs=s.crs, transform=tr, nodata=np.nan)
            ds.write(arr.astype(np.float32), 1)
            mems.append(ds)
        mos, tr = merge(mems, nodata=np.nan, method="first")
        for d in mems: d.close()
        print(f"  mosaic @ {size}: {mos.shape[2]} x {mos.shape[1]} in {time.time() - t0:.0f}s")
        return mos[0], tr

    z, tr = mosaic_at(a.height_size)
    h, w = z.shape
    valid = np.isfinite(z)
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
    print(f"height grid {w} x {h}, cell {tr.a:.3f} m; elevation {zmin:.1f}..{zmax:.1f} m; "
          f"nodata {100 * (~valid).mean():.1f}%")
    # 0 is reserved for nodata; valid elevations map to 1..65535.
    zf = np.where(valid, z, zmin)
    q = (1 + np.round((zf - zmin) / (zmax - zmin) * 65534)).astype(np.uint16)
    q[~valid] = 0
    q.astype("<u2").tofile(os.path.join(a.out, "heightmap.bin"))
    del z, zf, q

    zt, trt = mosaic_at(a.texture_size)
    validt = np.isfinite(zt)
    zt = np.where(validt, zt, zmin).astype(np.float32)
    hs = hillshade(zt, trt.a).astype(np.float32)
    hs[~validt] = 0.25
    Image.fromarray((hs * 255).astype(np.uint8)).save(os.path.join(a.out, "hillshade.jpg"), quality=90)
    tint = hypsometric(zt, zmin, zmax)
    del zt
    tex = np.clip(tint * (0.35 + 0.65 * hs)[..., None], 0, 255).astype(np.uint8)
    del tint, hs
    tex[~validt] = (40, 44, 52)
    img = Image.fromarray(tex)
    img.save(os.path.join(a.out, "texture.jpg"), quality=90)
    img.resize((1400, 1400 * tex.shape[0] // tex.shape[1])).save(os.path.join(a.out, "preview.png"))

    meta = {
        "name": a.name,
        "width": w, "height": h,
        "cellsize": tr.a,
        "bounds": {"left": left, "right": right, "bottom": bottom, "top": top},
        "extent_m": {"x": right - left, "y": top - bottom},
        "zmin": zmin, "zmax": zmax, "nodata": 0,
        "crs": str(crs),
        "texture": "texture.jpg", "hillshade": "hillshade.jpg",
        "tiles": [os.path.basename(p) for p in tifs],
        "source": "USGS 3DEP 1 m lidar",
    }
    old = os.path.join(a.out, "meta.json")
    if os.path.exists(old):   # keep keys other tools added, e.g. NAIP imagery from fetch_naip.py
        prev = json.load(open(old))
        if prev.get("naip") and os.path.exists(os.path.join(a.out, prev["naip"])):
            meta["naip"] = prev["naip"]; meta["naip_credit"] = prev.get("naip_credit", "")
            if prev.get("naip_bounds"): meta["naip_bounds"] = prev["naip_bounds"]
    with open(old, "w") as f:
        json.dump(meta, f, indent=2)
    print("wrote", sorted(os.listdir(a.out)))


if __name__ == "__main__":
    main()
