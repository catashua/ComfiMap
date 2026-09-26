# Route Discomfort Finder + Pareto Filter

This folder contains two scripts that work together as a pipeline:

1. **`give_routes_discomfort_geopandas.py`** — given a street/path network
   GeoPackage and a start/end coordinate, finds every reasonable alternative
   route between them and writes each one out as its own GeoPackage file
   into an **`all_routes/`** folder.
2. **`filter_pareto_routes.py`** — reads everything in `all_routes/`,
   figures out which of those routes are actually worth looking at (the
   Pareto frontier of distance vs. discomfort), and copies just those into
   a **`pareto_routes/`** folder.

Run them in that order: `give_routes...` first, `filter_pareto_routes...`
second.

```
network.gpkg
     │
     ▼
give_routes_discomfort_geopandas.py
     │
     ▼
 all_routes/              <- every candidate route
     │
     ▼
filter_pareto_routes.py
     │
     ▼
 pareto_routes/           <- only the non-dominated, worthwhile routes
```

---

## Requirements

```
pip install geopandas shapely
```

Both scripts are plain Python — no QGIS installation needed.

---

## 1. `give_routes_discomfort_geopandas.py`

### What it does

Given a line-network GeoPackage (streets, sidewalks, trails — anything made
of connected line segments) and a start/end coordinate pair, this script:

1. Builds a graph from the network's line segments.
2. Snaps the start and end coordinates onto the nearest segment, splitting
   that segment at the snap point so the route doesn't have to start/end on
   an existing vertex.
3. Finds the shortest possible distance between the two points (a normal
   Dijkstra run).
4. Searches for every other simple route that's no more than
   `stretch_factor` times longer than that shortest route (e.g. `1.1` =
   routes up to 10% longer are considered "reasonable alternatives"),
   tracking a **discomfort** value (e.g. thermal comfort, shade, noise —
   whatever your `discomfort_field` represents) along each one.
5. Writes each surviving route out as its own GeoPackage file, with
   `total_dist` and `total_discomfort` attributes attached to every
   feature in that file.

The search is pruned using a memoized "shortest remaining distance to the
destination" table, so it doesn't waste time exploring branches that can't
possibly finish within the distance budget.

### Your network file needs

- A line geometry column (LineString or MultiLineString).
- A field with each segment's length (e.g. `ped_length`) — if missing or
  unreadable, the script falls back to the geometry's own length.
- A field with each segment's discomfort value (e.g.
  `weighted_discomfort`) — if missing, discomfort defaults to `0`.

### How to run it

**Put the output straight into `all_routes/`** by passing that as the
output folder:

```bash
python give_routes_discomfort_geopandas.py network.gpkg all_routes \
    --input-layer network \
    --start 582933.54 4507092.79 \
    --end   583459.91 4507239.99 \
    --stretch-factor 1.1 \
    --time-stamp 18 \
    --length-field ped_length \
    --discomfort-field weighted_discomfort
```

Or from Python:

```python
from give_routes_discomfort_geopandas import find_alternative_discomfort_routes

find_alternative_discomfort_routes(
    input_gpkg="network.gpkg",
    output_dir="all_routes",          # <-- must be "all_routes" for the next step
    input_layer="network",
    start_coord=(582933.54, 4507092.79),
    end_coord=(583459.91, 4507239.99),
    stretch_factor=1.1,
    time_stamp=18,                    # optional label, e.g. hour of day; can be None
    length_field="ped_length",
    discomfort_field="weighted_discomfort",
)
```

Notes:

- `--input-layer` can be omitted if your GeoPackage only has one layer.
  Check what layers a file has with:
  ```python
  import fiona
  print(fiona.listlayers("network.gpkg"))
  ```
- `--time-stamp` is just a label used in output filenames (handy if you're
  running this for several times of day) — leave it out if you don't need
  it.
- Every file it writes into `all_routes/` is named
  `Alternative_Route_<n>.gpkg` and carries `total_dist` / `total_discomfort`
  attributes — that's what the next script reads.

---

## 2. `filter_pareto_routes.py`

### What it does

Reads every `.gpkg` file in a folder (`all_routes/`), pulls out each
route's `total_dist` and `total_discomfort`, and keeps only the ones on the
**Pareto frontier**: a route survives only if no other route is at least as
good on *both* distance and discomfort. In other words, a route gets
dropped only when some other route beats it on one measure without being
worse on the other — never a difficult numerical trade-off, just outright
"strictly worse, don't bother."

It does this efficiently: sort all routes by distance, then walk through
once keeping a running "best discomfort so far" — a route is kept only if
it beats that running best. This is `O(n log n)`, not the slower
`O(n²)` approach of comparing every route against every other route.

The surviving files are **copied** (not moved) into a new folder — your
full set of candidate routes in `all_routes/` is left untouched.

### How to run it

```bash
python filter_pareto_routes.py all_routes pareto_routes
```

Or from Python:

```python
from filter_pareto_routes import filter_routes_to_pareto_frontier

frontier = filter_routes_to_pareto_frontier("all_routes", "pareto_routes")
```

This creates `pareto_routes/` (if it doesn't already exist) and copies just
the frontier routes into it, printing each one's distance and discomfort
as it goes. Any file in `all_routes/` that isn't a readable route (missing
the `total_dist`/`total_discomfort` columns, or not a valid GeoPackage) is
skipped with a printed reason rather than stopping the whole run.

---

## Full example, start to finish

```bash
python give_routes_discomfort_geopandas.py network.gpkg all_routes \
    --start 582933.54 4507092.79 \
    --end   583459.91 4507239.99 \
    --stretch-factor 1.15

python filter_pareto_routes.py all_routes pareto_routes
```

After this, `pareto_routes/` contains only the routes genuinely worth
comparing — for any route left out, something in `pareto_routes/` is at
least as short *and* at least as comfortable.

## Tips

- If `pareto_routes/` ends up with very few files, your `all_routes/` set
  might not have much spread in distance — try a slightly larger
  `--stretch-factor` on the first script to generate more candidates.
- If you're comparing routes across several times of day, run the first
  script once per time stamp into separate `all_routes_<time>/` folders
  (using `--time-stamp` to label the files), then run the filter on each
  one separately — discomfort at 6am and 6pm isn't the same thing and
  shouldn't be filtered together.
