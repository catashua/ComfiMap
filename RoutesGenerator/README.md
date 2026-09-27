# Running `find_routes2` and `filter_pareto_routes`

This README explains how to run the route-generation and
Pareto-filtering scripts using the same setup and parameter values
demonstrated by `ClaudeTestesr.py`.

## 1. What the two scripts do

The workflow has two stages:

1.  **`find_routes2.py`** reads a pedestrian-network GeoPackage, finds
    the shortest path between a start and end coordinate, and generates
    additional simple paths that are within a specified percentage of
    the shortest path.
2.  **`filter_pareto_routes.py`** examines the generated route
    GeoPackages and keeps only the routes on the Pareto frontier,
    balancing total route length and total discomfort (`total_cd`).

The path finder expects an input GeoPackage whose edges contain the
fields `u`, `v`, `Shape_Leng`, `cd`, and geometry. It writes one
GeoPackage per qualifying path plus a `summary.csv` file.

The Pareto filter expects the generated route GeoPackages to contain
`total_length` and `total_cd` attributes.

------------------------------------------------------------------------

## 2. Required files

A typical directory should look like this:

``` text
project/
├── find_routes2.py
├── filter_pareto_routes.py
├── ClaudeTestesr.py
└── route_08_12.gpkg
```

After running the workflow, the directories will look approximately
like:

``` text
project/
├── all_routes/
│   ├── path_000_...
│   ├── path_001_...
│   ├── ...
│   └── summary.csv
│
└── optimal_routes/
    ├── path_...
    ├── path_...
    └── ...
```

------------------------------------------------------------------------

## 3. Python environment

The scripts import these Python packages:

-   `geopandas`
-   `networkx`
-   `shapely`
-   `pyproj`

A normal installation can be made with:

``` bash
pip install geopandas networkx shapely pyproj
```

If you are using a Conda environment, the equivalent packages can be
installed with Conda/Conda-Forge.

Run the commands from the directory containing the Python scripts, or
provide the appropriate paths to the files.

------------------------------------------------------------------------

# Part 1: Running `find_routes2.py`

## 4. Command-line usage

`find_routes2.py` accepts the following arguments:

``` text
--input
--start-x
--start-y
--end-x
--end-y
--output-dir
--percent
--max-paths
--coords-crs
--clear-output
```

A basic command is:

``` bash
python find_routes2.py \
    --input route_08_12.gpkg \
    --start-x 583459.91 \
    --start-y 4507239.99 \
    --end-x 583309.0 \
    --end-y 4506685.6 \
    --output-dir ./all_routes \
    --percent 10 \
    --max-paths 100 \
    --coords-crs EPSG:32618 \
    --clear-output
```

On Windows Command Prompt, the same command can be written on one line:

``` cmd
python find_routes2.py --input route_08_12.gpkg --start-x 583459.91 --start-y 4507239.99 --end-x 583309.0 --end-y 4506685.6 --output-dir ./all_routes --percent 10 --max-paths 100 --coords-crs EPSG:32618 --clear-output
```

## 5. What the arguments mean

### `--input`

The pedestrian-network GeoPackage.

Example:

``` text
--input route_08_12.gpkg
```

The input layer is expected to contain:

``` text
u
v
Shape_Leng
cd
geometry
```

`Shape_Leng` is used as the walking-distance weight, while `cd` is
accumulated to calculate route discomfort.

### `--start-x` and `--start-y`

The starting coordinate.

With the default `EPSG:32618`, these are X/Y coordinates in the graph's
coordinate system:

``` text
start-x = easting
start-y = northing
```

The example test configuration uses:

``` text
583459.91, 4507239.99
```

### `--end-x` and `--end-y`

The destination coordinate.

The example test configuration uses:

``` text
583309.0, 4506685.6
```

### `--output-dir`

Directory where the generated route GeoPackages and `summary.csv` will
be written.

Example:

``` text
--output-dir ./all_routes
```

### `--percent`

Controls how far a route is allowed to be from the shortest route.

For example:

``` text
--percent 10
```

means that routes up to 10% longer than the shortest path are eligible.

The script calculates:

``` text
threshold = shortest_length × (1 + percent / 100)
```

### `--max-paths`

Maximum number of near-shortest paths to generate.

The test configuration uses:

``` text
--max-paths 100
```

The script's default is 50.

### `--coords-crs`

CRS of the start/end coordinates.

The test configuration uses:

``` text
--coords-crs EPSG:32618
```

This means the supplied X/Y coordinates are already in UTM Zone 18N
coordinates.

If your coordinates are longitude/latitude in WGS84, use:

``` text
--coords-crs EPSG:4326
```

In that case:

``` text
--start-x = longitude
--start-y = latitude
--end-x   = longitude
--end-y   = latitude
```

### `--clear-output`

If included, the existing output directory is deleted before the new
routes are written.

For example:

``` text
--clear-output
```

Use this when you want `all_routes` to contain only the routes from the
current run.

------------------------------------------------------------------------

## 6. What happens when `find_routes2.py` runs

The script:

1.  Loads the pedestrian-network GeoPackage.
2.  Builds a graph from its `u` and `v` node fields.
3.  Uses `Shape_Leng` as the route-length weight.
4.  Snaps the supplied start and end coordinates to the nearest graph
    nodes.
5.  Finds the shortest path.
6.  Calculates the allowed length threshold from `--percent`.
7.  Finds additional simple paths within that threshold.
8.  Limits the number of returned paths using `--max-paths`.
9.  Writes each path to its own GeoPackage.
10. Writes `summary.csv` containing route metrics.

The output GeoPackages contain the route segments plus:

``` text
path_rank
path_order
total_length
total_cd
```

The filename also records the route's length and discomfort.

For example:

``` text
path_003_len512.4_cd123.456.gpkg
```

------------------------------------------------------------------------

# Part 2: Running `filter_pareto_routes.py`

## 7. What the Pareto filter does

After `find_routes2.py` creates a collection of routes,
`filter_pareto_routes.py` compares them using two metrics:

-   `total_length`
-   `total_cd`

A route remains on the Pareto frontier when no previously considered
route has both:

-   equal or shorter distance, and
-   equal or lower discomfort,

with a strict improvement in discomfort used by the script's
sort-and-sweep implementation.

The script sorts routes by distance and keeps a route whenever its
discomfort is lower than the best discomfort encountered so far.

------------------------------------------------------------------------

## 8. Running the Pareto filter

The intended command-line interface is:

``` bash
python filter_pareto_routes.py routes_folder pareto_routes_folder
```

For this workflow:

``` bash
python filter_pareto_routes.py ./all_routes ./optimal_routes
```

This reads the `.gpkg` files in:

``` text
./all_routes
```

and copies the Pareto-frontier files into:

``` text
./optimal_routes
```

The output directory is created if necessary.

**Important:** in the current version of `filter_pareto_routes.py`, the
CLI argument parsing is commented out in the `__main__` section. The
active code instead runs:

``` python
filter_routes_to_pareto_frontier("./all_routes", "./optimal_routes")
```

Therefore, running:

``` bash
python filter_pareto_routes.py
```

currently uses `./all_routes` and `./optimal_routes` directly.

If you want to use different directories from the command line, the
commented `_parse_args()` lines need to be enabled.

------------------------------------------------------------------------

# Part 3: Running the complete workflow

## 9. Recommended two-step workflow

First generate the near-shortest routes:

``` bash
python find_routes2.py --input route_08_12.gpkg --start-x 583459.91 --start-y 4507239.99 --end-x 583309.0 --end-y 4506685.6 --output-dir ./all_routes --percent 10 --max-paths 100 --coords-crs EPSG:32618 --clear-output
```

Then filter them:

``` bash
python filter_pareto_routes.py
```

The final result is:

``` text
all_routes/
    all generated routes
    summary.csv

optimal_routes/
    Pareto-frontier routes
```

------------------------------------------------------------------------

# Part 4: Using `ClaudeTestesr.py`

## 10. One-command test workflow

`ClaudeTestesr.py` demonstrates the same workflow from Python rather
than from two separate command-line calls.

Its configuration is:

``` python
config = {
    "input_gpkg": "route_08_12.gpkg",
    "start_x": 583459.91,
    "start_y": 4507239.99,
    "end_x": 583309.0,
    "end_y": 4506685.6,
    "output_dir": "./all_routes",
    "percent": 10.0,
    "max_paths": 100,
    "coords_crs": "EPSG:32618",
    "clear_output": True
}
```

The test script calls `find_routes2.run(...)` and then calls:

``` python
filter_pareto_routes.filter_routes_to_pareto_frontier(
    "./all_routes",
    "./optimal_routes"
)
```

So you can run the complete example with:

``` bash
python ClaudeTestesr.py
```

Make sure `route_08_12.gpkg` is in the same working directory, or change
the `input_gpkg` value in the configuration.

------------------------------------------------------------------------

## 11. Expected output from the test script

During the route-finding stage, the script reports information such as:

``` text
Start snapped to node ...
End snapped to node ...
Shortest path length: ... m
Threshold (10.0% over shortest): ... m
Found ... path(s) within threshold (capped at max_paths=100)
```

It then reports where the generated files and summary are located.

The Pareto-filtering stage reports:

``` text
... route(s) read, ... on the Pareto frontier.
Copied to: ./optimal_routes
```

The `optimal_routes` directory therefore contains the subset of
generated routes that remain on the Pareto frontier.

------------------------------------------------------------------------

# 12. Important coordinate note

The example uses:

``` text
EPSG:32618
```

and coordinates such as:

``` text
583459.91, 4507239.99
```

These are **not latitude/longitude values**.

If you instead have coordinates such as:

``` text
-74.0113, 40.7075
```

you should use:

``` bash
--coords-crs EPSG:4326
```

and supply them as:

``` text
--start-x -74.0113
--start-y 40.7075
```

That is:

``` text
X = longitude
Y = latitude
```

The script transforms those coordinates into the graph's CRS before
snapping them to graph nodes.

------------------------------------------------------------------------

# 13. Troubleshooting

### `Input gpkg is missing expected column(s)`

Check that the input GeoPackage contains:

``` text
u
v
Shape_Leng
cd
geometry
```

### `No path exists between start and end nodes`

The start/end coordinates may snap to disconnected portions of the
pedestrian network.

Check the coordinates and network connectivity.

### `Start and end snap to the same graph node`

The two supplied coordinates are close enough to snap to the same
network node. Use coordinates farther apart.

### Pareto filter skips a file

Every route GeoPackage processed by the Pareto filter needs usable:

``` text
total_length
total_cd
```

attributes.

The filter reports skipped files and continues processing the others.

### Old Pareto routes remain

The Pareto filter clears the output directory before copying the new
Pareto routes, while preserving `.gitignore`.

------------------------------------------------------------------------

# 14. Quick reference

### Generate routes

``` bash
python find_routes2.py \
    --input INPUT.gpkg \
    --start-x START_X \
    --start-y START_Y \
    --end-x END_X \
    --end-y END_Y \
    --output-dir ./all_routes \
    --percent 10 \
    --max-paths 100 \
    --coords-crs EPSG:32618 \
    --clear-output
```

### Filter routes

``` bash
python filter_pareto_routes.py
```

### Run the complete test example

``` bash
python ClaudeTestesr.py
```

### Main output

``` text
all_routes/
    *.gpkg
    summary.csv

optimal_routes/
    *.gpkg
```
