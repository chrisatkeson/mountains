# mountains

Interactive 3D view of USGS 3DEP 1 m lidar elevation for the Sangre de Cristo
range and Wet Mountain Valley in southern Colorado, built from 63 tiles across
four lidar projects (roughly 70 × 60 km).

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install rasterio numpy pillow
```

## Download the tiles

```sh
./scripts/download.sh
```

Reads `data/tiles.txt`, fetches 8 at a time into `data/raw/`, and skips files
already present. Each tile is a 10 km square at 1 m, EPSG:26913 (UTM 13N).
Expect roughly 10 GB. Several cells are covered by more than one lidar
project; the mosaic prefers them in the order listed in `PROJECT_PRIORITY` at
the top of `scripts/process_dem.py` and uses the others to fill gaps.

## Build the viewer assets

```sh
.venv/bin/python scripts/process_dem.py                     # 8192 px heightmap (~8.5 m), 8192 px texture
.venv/bin/python scripts/process_dem.py --height-size 4096  # lighter: ~17 m cells, 29 MB heightmap
```

Writes `viewer/data/`: `heightmap.bin` (Uint16, 0 = nodata), `texture.jpg`
(hillshade + hypsometric tint), `hillshade.jpg`, `meta.json`, `preview.png`.

## Build the 1 m tile pyramid

```sh
.venv/bin/python scripts/build_tiles.py        # ~3 minutes, ~5 GB in viewer/data/tiles/
```

Cuts the mosaic into 512-cell tiles at 7 levels (1 m up to 64 m). Level 0 is
read straight from the GeoTIFFs; each coarser level is an exact 2×2 average of
the one below. Tiles carry a 1-cell apron so normals are seamless, are stored
as gzip-compressed 16-bit samples, and `tiles/index.json` holds the layout and
per-tile elevation range. Requires `process_dem.py` to have run first, since
the viewer still uses its coarse heightmap for picking before fine tiles load.

## Aerial imagery (optional)

```sh
.venv/bin/python scripts/fetch_naip.py            # 16384 px wide, ~4.3 m/px, ~90 MB
```

Fetches USDA NAIP orthoimagery for the mosaic extent from the USGS National
Map ImageServer in 2000 px tiles and stitches them into `viewer/data/naip.jpg`.
The viewer uses it as the default texture when present, rendered unlit because
the photography already contains the sun; a fixed northwest sun lights the other
texture modes.

## Route planning

The Routes section of the panel plans off-trail lines on the lidar terrain:

- **Start route**, then click the terrain to add waypoints; drag a waypoint to
  move it; click one and press Delete to remove it; Undo removes the last.
- The line is draped on the heightfield every 2 m and coloured by slope
  (green under 20°, yellow around 25°, red near 45°, magenta above). Stats show
  distance, gain and loss (3 m hysteresis so lidar noise doesn't inflate them),
  the steepest 20 m stretch, and an elevation profile.
- **Save** keeps routes in the browser (localStorage) by name; the URL carries
  the saved name, or the waypoints themselves for short unsaved routes.
- **Export GPX** writes waypoints plus a draped track with lidar elevations in
  WGS84, which Gaia GPS, Garmin and similar devices import directly. **Import
  GPX** loads a route, track, or waypoints from such a file.

Elevations are bare earth: the planner knows slope and cliffs but nothing
about vegetation, deadfall, or snow.

## Full-resolution imagery tiles (optional, slow)

```sh
nohup .venv/bin/python scripts/fetch_naip_tiles.py > data/fetch_naip_tiles.log 2>&1 &
```

Fetches NAIP at 0.5 m/px as 1024 px tiles matching the terrain tiles, nearest
the Crestones first, then builds coarser levels by averaging. About 1,840
requests and 2 to 3 hours for level 0; roughly 5 GB in `viewer/data/imagery/`.
Safe to stop and resume. Each drawn terrain tile samples its own imagery tile,
or the nearest loaded ancestor, and falls back to the global image until the
tiles exist.

## Cliff detail

Orthoimagery carries no information on near-vertical faces, so draping it over
cliffs produces vertical streaks. With "Cliff shading" set to On (default Off), the fragment shader
blends faces steeper than about 40° to a triplanar-mapped procedural rock
texture (`viewer/data/rock.png`, from `scripts/make_rock_texture.py`) tinted
by the blurred local aerial colour, and lights those faces from the full
resolution lidar normal with a fixed northwest sun. Flat ground keeps the photo.

## View

```sh
cd viewer && python3 -m http.server 8000
```

Open http://localhost:8000. The viewer walks a quadtree over the tile pyramid
every frame: a tile is split into its four children when one of its cells would
cover more than the "Mesh detail" target in screen pixels, and only once all
four children have loaded. Tiles stream in nearest-first (8 in flight), up to
700 stay cached, and each is drawn with one shared grid geometry whose vertex
shader reads elevation from the tile's own heightmap texture. Normals come from
neighbouring texels, so lighting is always at the tile's full resolution. On
"Full" the terrain within about a kilometre of the camera is drawn at 1 m. Drag to orbit, right-drag to pan, scroll to zoom,
`R` to reset, `T` for a top-down view. The panel controls mesh density,
texture mode, cliff shading and wireframe. Hovering
shows elevation and UTM coordinates sampled from the full heightmap.

The URL always mirrors the current camera (map or ground view) and every panel
setting, so a reload, bookmark, or the "Copy view link" button reproduces the
exact view. Useful for before/after comparisons across a hard refresh.

Click any point to stand on it at eye level. On the ground, drag to look
around, use WASD or arrow keys to walk (Shift to run), scroll to zoom the field
of view, and press `Esc` or the panel button to return to the map. The URL
updates with `?ground=<easting>,<northing>&yaw=<degrees>` so a viewpoint can be
bookmarked or shared.
