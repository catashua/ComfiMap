#!/usr/bin/env python3
"""
Filters a folder of route GeoPackages (as produced by
give_routes_discomfort_geopandas.find_alternative_discomfort_routes) down to
just the ones on the Pareto frontier in (total_dist, total_discomfort)
space, and copies the surviving files into a separate output folder.

Each input .gpkg is expected to contain a "total_dist" and "total_discomfort"
attribute on its features (all rows of a given route share the same values,
since those columns describe the whole route, not an individual segment).

Uses the O(n log n) sort-and-sweep Pareto frontier: sort routes by distance
ascending, then keep a route only if its discomfort is strictly lower than
the lowest discomfort seen among all routes considered so far.

Usage (CLI):
    python filter_pareto_routes.py routes_folder pareto_routes_folder

Or import and call `filter_routes_to_pareto_frontier(...)` directly.
"""

import argparse
import os
import shutil

import geopandas as gpd


def load_route_metrics(gpkg_path):
    """Read a route GeoPackage and return (total_dist, total_discomfort)."""
    gdf = gpd.read_file(gpkg_path)
    if gdf.empty:
        raise ValueError("file contains no features")
    if "total_dist" not in gdf.columns or "total_discomfort" not in gdf.columns:
        raise ValueError("missing 'total_dist' / 'total_discomfort' columns")

    row = gdf.iloc[0]
    return float(row["total_dist"]), float(row["total_discomfort"])


def pareto_frontier(results):
    """
    results: list of (total_dist, total_discomfort, path)

    O(n log n) sort-and-sweep: sort by distance ascending, then keep a
    route only if it strictly improves on the best discomfort seen so far.
    Returns the surviving subset, sorted by distance ascending.
    """
    sorted_results = sorted(results, key=lambda r: (r[0], r[1]))
    frontier = []
    best_discomfort_so_far = float("inf")
    for dist, discomfort, path in sorted_results:
        if discomfort < best_discomfort_so_far:
            frontier.append((dist, discomfort, path))
            best_discomfort_so_far = discomfort
    return frontier


def filter_routes_to_pareto_frontier(input_dir, output_dir):
    """
    Reads every .gpkg in `input_dir`, computes the Pareto frontier over
    (total_dist, total_discomfort), and copies the surviving files into
    `output_dir` (created if it doesn't already exist).

    Returns the list of (total_dist, total_discomfort, source_path) tuples
    that made the frontier.
    """
    gpkg_names = sorted(f for f in os.listdir(input_dir) if f.lower().endswith(".gpkg"))
    if not gpkg_names:
        raise ValueError(f"No .gpkg files found in {input_dir}")

    results = []
    skipped = []
    for name in gpkg_names:
        path = os.path.join(input_dir, name)
        try:
            dist, discomfort = load_route_metrics(path)
            results.append((dist, discomfort, path))
        except Exception as e:  # noqa: BLE001 - report and continue past any unreadable file
            skipped.append((name, str(e)))

    if skipped:
        print(f"Skipped {len(skipped)} file(s):")
        for name, reason in skipped:
            print(f"  {name}: {reason}")

    if not results:
        raise ValueError("No route files with usable total_dist/total_discomfort data were found.")

    frontier = pareto_frontier(results)

    os.makedirs(output_dir, exist_ok=True)
    for _dist, _discomfort, path in frontier:
        shutil.copy2(path, os.path.join(output_dir, os.path.basename(path)))

    print(f"\n{len(results)} route(s) read, {len(frontier)} on the Pareto frontier.")
    print(f"Copied to: {output_dir}")
    for dist, discomfort, path in frontier:
        print(f"  {os.path.basename(path)}: dist={dist:.2f}, discomfort={discomfort:.2f}")

    return frontier


def _parse_args():
    parser = argparse.ArgumentParser(description="Filter a folder of route GeoPackages down to the Pareto frontier.")
    parser.add_argument("input_dir", help="Folder containing route .gpkg files.")
    parser.add_argument("output_dir", help="Folder to copy the Pareto-frontier .gpkg files into.")
    return parser.parse_args()


if __name__ == "__main__":
    #args = _parse_args()
    #filter_routes_to_pareto_frontier(args.input_dir, args.output_dir)
    filter_routes_to_pareto_frontier("./example_output", "./pareto_outputs")
