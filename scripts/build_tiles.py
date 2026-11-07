#!/usr/bin/env python
"""Cut the 1 m DEM mosaic into a tile pyramid for streaming in the viewer.

Level L has a cell size of 2**L metres. Each tile holds T x T cells plus a
1-cell apron on every side (so normals can be computed at tile edges), stored
as (T+2)^2 little-endian uint16 samples, gzip-compressed, with 0 = nodata and
1..65535 spanning [zmin, zmin + zrange]. Level 0 is read straight from the
source GeoTIFFs; every coarser level is a 2x2 nodata-aware average of the level
below it, so all levels line up exactly.

Output: viewer/data/tiles/<L>/<tx>_<ty>.bin.gz plus tiles/index.json.
"""
import argparse, glob, gzip, json, math, os, sys, time, warnings
from multiprocessing import Pool
import numpy as np
import rasterio
from rasterio.windows import Window

sys.path.insert(0, os.path.dirname(__file__))
from process_dem import priority  # noqa: E402

T = 512
RAW = OUT = None
SOURCES = []          # (path, col_off, row_off, width, height) in mosaic pixel coords, priority order
Q = {}                # zmin, zrange
_open = {}


def init_worker(raw, out, sources, q):
    """Pool initializer: worker processes are spawned fresh on macOS, so pass config explicitly."""
    global RAW, OUT, SOURCES, Q
    RAW, OUT, SOURCES, Q = raw, out, sources, q


def src(path):
    if path not in _open:
        _open[path] = rasterio.open(path)
    return _open[path]


def quantize(z):
    q = np.where(np.isfinite(z), 1 + np.round((z - Q["zmin"]) / Q["zrange"] * 65534), 0)
    return np.clip(q, 0, 65535).astype("<u2")


def tile_path(L, tx, ty):
    return os.path.join(OUT, str(L), f"{tx}_{ty}.bin.gz")


def write_tile(L, tx, ty, q):
    os.makedirs(os.path.dirname(tile_path(L, tx, ty)), exist_ok=True)
    with gzip.open(tile_path(L, tx, ty), "wb", compresslevel=6) as f:
        f.write(q.tobytes())


def read_tile(L, tx, ty):
    p = tile_path(L, tx, ty)
    if not os.path.exists(p):
        return None
    with gzip.open(p, "rb") as f:
        return np.frombuffer(f.read(), dtype="<u2").reshape(T + 2, T + 2)


def level0_job(args):
    tx, ty = args
    c0, r0, n = tx * T - 1, ty * T - 1, T + 2
    out = np.full((n, n), np.nan, dtype=np.float32)
    for path, sc, sr, sw, sh in SOURCES:
        ic0, ic1 = max(c0, sc), min(c0 + n, sc + sw)
        ir0, ir1 = max(r0, sr), min(r0 + n, sr + sh)
        if ic1 <= ic0 or ir1 <= ir0:
            continue
        arr = src(path).read(1, window=Window(ic0 - sc, ir0 - sr, ic1 - ic0, ir1 - ir0), masked=True).filled(np.nan)
        dest = out[ir0 - r0:ir1 - r0, ic0 - c0:ic1 - c0]
        m = np.isnan(dest) & np.isfinite(arr)
        dest[m] = arr[m]
    return finish(0, tx, ty, out)


def finish(L, tx, ty, z):
    valid = np.isfinite(z)
    lo, hi = (float(np.nanmin(z)), float(np.nanmax(z))) if valid.any() else (None, None)
    write_tile(L, tx, ty, quantize(z))
    return tx, ty, lo, hi


def region(L, c0, r0, w, h, nx, ny):
    """Assemble a w x h window of level-L cells (no aprons) from tiles; 0 outside."""
    out = np.zeros((h, w), dtype="<u2")
    for ty in range(max(0, r0 // T), min(ny, (r0 + h - 1) // T + 1)):
        for tx in range(max(0, c0 // T), min(nx, (c0 + w - 1) // T + 1)):
            t = read_tile(L, tx, ty)
            if t is None:
                continue
            ic0, ic1 = max(c0, tx * T), min(c0 + w, tx * T + T)
            ir0, ir1 = max(r0, ty * T), min(r0 + h, ty * T + T)
            if ic1 <= ic0 or ir1 <= ir0:
                continue
            out[ir0 - r0:ir1 - r0, ic0 - c0:ic1 - c0] = t[1 + ir0 - ty * T:1 + ir1 - ty * T, 1 + ic0 - tx * T:1 + ic1 - tx * T]
    return out


def upper_job(args):
    L, tx, ty, nx_below, ny_below = args
    n = T + 2
    q = region(L - 1, (tx * T - 1) * 2, (ty * T - 1) * 2, 2 * n, 2 * n, nx_below, ny_below)
    z = np.where(q == 0, np.nan, Q["zmin"] + (q.astype(np.float32) - 1) / 65534 * Q["zrange"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        z2 = np.nanmean(z.reshape(n, 2, n, 2), axis=(1, 3))
    return finish(L, tx, ty, z2)


def main():
    global RAW, OUT, SOURCES, Q
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="viewer/data/tiles")
    ap.add_argument("--meta", default="viewer/data/meta.json")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--start-level", type=int, default=0, help="resume: skip levels below this")
    a = ap.parse_args()
    RAW, OUT = a.raw, a.out
    os.makedirs(OUT, exist_ok=True)

    meta = json.load(open(a.meta))
    b = meta["bounds"]
    tifs = sorted(glob.glob(os.path.join(RAW, "*.tif")), key=priority)
    for p in tifs:
        with rasterio.open(p) as s:
            if abs(s.res[0] - 1) > 1e-6:
                sys.exit(f"{p}: expected 1 m cells")
            co, ro = (s.bounds.left - b["left"]), (b["top"] - s.bounds.top)
            if abs(co - round(co)) > 1e-3 or abs(ro - round(ro)) > 1e-3:
                sys.exit(f"{p}: not aligned to the mosaic grid")
            SOURCES.append((p, int(round(co)), int(round(ro)), s.width, s.height))
    W0, H0 = int(round(b["right"] - b["left"])), int(round(b["top"] - b["bottom"]))
    # Fixed quantisation range with headroom, since the 1 m extremes exceed the downsampled ones.
    Q = {"zmin": math.floor(meta["zmin"]) - 50.0, "zrange": float(math.ceil(meta["zmax"]) - math.floor(meta["zmin"]) + 100)}

    levels = []
    L = 0
    while True:
        WL, HL = math.ceil(W0 / 2 ** L), math.ceil(H0 / 2 ** L)
        nx, ny = math.ceil(WL / T), math.ceil(HL / T)
        levels.append({"level": L, "cell": 2 ** L, "width": WL, "height": HL, "nx": nx, "ny": ny})
        if max(nx, ny) <= 3:
            break
        L += 1
    print(f"mosaic {W0} x {H0} @ 1 m from {len(SOURCES)} sources; {len(levels)} levels, "
          f"{sum(l['nx'] * l['ny'] for l in levels)} tiles of {T} cells", flush=True)

    index_path = os.path.join(OUT, "index.json")
    index = json.load(open(index_path)) if os.path.exists(index_path) else {}
    index.update({"tileSize": T, "apron": 1, "zmin": Q["zmin"], "zrange": Q["zrange"], "built": int(time.time()),
                  "bounds": b, "crs": meta["crs"], "levels": levels})
    index.setdefault("minmax", {})

    with Pool(a.workers, initializer=init_worker, initargs=(RAW, OUT, SOURCES, Q)) as pool:
        for lv in levels:
            L = lv["level"]
            if L < a.start_level:
                continue
            t0 = time.time()
            nx, ny = lv["nx"], lv["ny"]
            if L == 0:
                jobs = [(tx, ty) for ty in range(ny) for tx in range(nx)]
                it = pool.imap_unordered(level0_job, jobs, chunksize=4)
            else:
                below = levels[L - 1]
                jobs = [(L, tx, ty, below["nx"], below["ny"]) for ty in range(ny) for tx in range(nx)]
                it = pool.imap_unordered(upper_job, jobs, chunksize=4)
            mm = [None] * (nx * ny)
            for k, (tx, ty, lo, hi) in enumerate(it, 1):
                mm[ty * nx + tx] = [round(lo), round(hi)] if lo is not None else None
                if k % 500 == 0 or k == len(jobs):
                    print(f"  level {L}: {k}/{len(jobs)} tiles, {time.time() - t0:.0f}s", flush=True)
            index["minmax"][str(L)] = mm
            json.dump(index, open(index_path, "w"))
            print(f"level {L} done in {time.time() - t0:.0f}s", flush=True)
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(OUT) for f in fs)
    print(f"pyramid complete: {size / 1e9:.2f} GB in {OUT}")


if __name__ == "__main__":
    main()
