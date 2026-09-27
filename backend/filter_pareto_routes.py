#!/usr/bin/env python3
"""
Filters a folder of route GeoPackages (as produced by
give_routes_discomfort_geopandas.find_alternative_discomfort_routes) down to
just the ones on the Pareto frontier in (total_length, total_cd)
space, and copies the surviving files into a separate output folder.

Each input .gpkg is expected to contain a "total_length" and "total_cd"
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
    """Read a route GeoPackage and return (total_length, total_cd)."""
    gdf = gpd.read_file(gpkg_path)
    if gdf.empty:
        raise ValueError("file contains no features")
    if "total_length" not in gdf.columns or "total_cd" not in gdf.columns:
        raise ValueError("missing 'total_length' / 'total_cd' columns")

    row = gdf.iloc[0]
    return float(row["total_length"]), float(row["total_cd"])


def pareto_frontier(results):
    """
    results: list of (total_length, total_cd, path)

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
    (total_length, total_cd), and copies the surviving files into
    `output_dir` (created if it doesn't already exist).

    Returns the list of (total_length, total_cd, source_path) tuples
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
        raise ValueError("No route files with usable total_length/total_cd data were found.")

    frontier = pareto_frontier(results)

    # 1. Ensure output folder exists
    os.makedirs(output_dir, exist_ok=True)

    # 2. Clean out old files in output_dir, preserving .gitignore
    for entry in os.listdir(output_dir):
        if entry == ".gitignore":
            continue
        item_path = os.path.join(output_dir, entry)
        try:
            if os.path.isfile(item_path) or os.path.islink(item_path):
                os.unlink(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)
        except Exception as e:
            print(f"Could not remove {item_path}: {e}")

    # 3. Copy new Pareto-optimal routes
    for _dist, _discomfort, path in frontier:
        shutil.copy2(path, os.path.join(output_dir, os.path.basename(path)))

    print(f"\n{len(results)} route(s) read, {len(frontier)} on the Pareto frontier.")
    print(f"Copied to: {output_dir}")
    for dist, discomfort, path in frontier:
        print(f"  {os.path.basename(path)}: dist={dist:.2f}, discomfort={discomfort:.2f}")

    return frontier

def get_pareto_routes_coordinates(paths_list):
    """
    Filters routes down to the Pareto frontier and extracts raw coordinate 
    arrays formatted exactly how your existing app.py matrix expects them.
    """
    # 1. Reuse your existing sort-and-sweep Pareto logic
    results = []
    for p in paths_list:
        results.append((p["total_length"], p["total_cd"], p))
        
    frontier = pareto_frontier(results)
    
    formatted_routes_output = []
    print("0")
    # 2. Extract standard coordinate matrices out of the geometry layers
    for dist, discomfort, path_item in frontier:
        gdf = path_item["gdf"]
        
        route_coordinates = []
        
        # Loop through each street segment line in the route option
        for geom in gdf.geometry:
            if geom.geom_type == 'LineString':
                # Leaflet maps read shapes in [Latitude, Longitude] format
                for coord in geom.coords:
                    route_coordinates.append([coord[1], coord[0]])
            elif geom.geom_type == 'MultiLineString':
                for line in geom.geoms:
                    for coord in line.coords:
                        route_coordinates.append([coord[1], coord[0]])
                '''for x, y in geom.coords:
                    route_coordinates.append([y, x])
            elif geom.geom_type == 'MultiLineString':
                for line in geom.geoms:
                    for x, y in line.coords:
                        route_coordinates.append([y, x])
                        '''
                

        # Package the result into the exact schema your app.py placeholder used
        formatted_routes_output.append({
            "name": f"Route Option {path_item['rank'] + 1}",
            "coordinates": route_coordinates,
            "duration": round(dist / 1.4), # Walk duration in seconds (~5 km/h)
            "mean_tmrt": round(discomfort, 2)
        })
    print("1")
    # SORT STEP: Sort the final optimal list by distance ascending (shortest first)
    formatted_routes_output.sort(key=lambda r: -1*r["duration"])
    print("2")
    # Clean up the display names so that "Route Option 1" is always the shortest option
    for index, route in enumerate(formatted_routes_output):
        route["name"] = f"Route Option {index + 1}"
    print("3")
    return formatted_routes_output



def _parse_args():
    parser = argparse.ArgumentParser(description="Filter a folder of route GeoPackages down to the Pareto frontier.")
    parser.add_argument("input_dir", help="Folder containing route .gpkg files.")
    parser.add_argument("output_dir", help="Folder to copy the Pareto-frontier .gpkg files into.")
    return parser.parse_args()


if __name__ == "__main__":
    #args = _parse_args()
    #filter_routes_to_pareto_frontier(args.input_dir, args.output_dir)
    filter_routes_to_pareto_frontier("./all_routes", "./optimal_routes")
