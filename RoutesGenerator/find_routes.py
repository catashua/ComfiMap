#!/usr/bin/env python3
"""
pedestrian_paths.py

Given a pedestrian-network .gpkg (edges with columns u, v, Shape_Leng, cd, geometry),
find the shortest path (by Shape_Leng) between an origin and destination coordinate,
then find every simple path whose total length is within X% of that shortest path.

For each qualifying path, write a .gpkg containing just that path's line segments,
plus a summary CSV listing each path's length and accumulated discomfort (sum of cd).

Input filename convention expected upstream: route_MM_HH.gpkg (month/hour), but this
script works on any .gpkg with the same schema.

Usage (CLI):
    python pedestrian_paths.py \
        --input route_08_08.gpkg \
        --start-lat 40.7075 --start-lon -74.0113 \
        --end-lat 40.7106 --end-lon -74.0086 \
        --output-dir ./paths_out \
        --percent 10 \
        --max-paths 50

Coordinates are given as WGS84 (lat/lon) by default; use --coords-crs to change that
(e.g. if you already have coordinates in the graph's native CRS, pass its EPSG code).
"""

import argparse
import os
import sys
import shutil
import itertools

import geopandas as gpd
import networkx as nx
from shapely.geometry import Point, LineString
from shapely.ops import linemerge
from pyproj import Transformer


LENGTH_COL = "Shape_Leng"
CD_COL = "cd"
U_COL = "u"
V_COL = "v"


def load_graph(gpkg_path):
    """Load edges from the gpkg and build an undirected MultiGraph.

    Each edge keeps its Shape_Leng (walking distance) and cd (discomfort) as
    attributes, plus the original geometry and row index so we can re-export
    exact geometries later.
    """
    gdf = gpd.read_file(gpkg_path)

    missing = [c for c in (U_COL, V_COL, LENGTH_COL, CD_COL) if c not in gdf.columns]
    if missing:
        raise ValueError(
            f"Input gpkg is missing expected column(s): {missing}. "
            f"Found columns: {list(gdf.columns)}"
        )

    G = nx.MultiGraph()
    G.graph["crs"] = gdf.crs

    for idx, row in gdf.iterrows():
        u, v = row[U_COL], row[V_COL]
        length = float(row[LENGTH_COL])
        cd = float(row[CD_COL])
        geom = row.geometry

        # Track node coordinates from the geometry endpoints so we can snap
        # arbitrary input coordinates to the nearest graph node later.
        line = _first_line(geom)
        if line is not None:
            coords = list(line.coords)
            _set_node_coord(G, u, coords[0])
            _set_node_coord(G, v, coords[-1])

        G.add_edge(u, v, key=idx, length=length, cd=cd, geometry=geom, row_index=idx)

    return gdf, G


def _first_line(geom):
    """Return a single LineString representing this geometry (handles MultiLineString)."""
    if geom is None:
        return None
    if geom.geom_type == "LineString":
        return geom
    if geom.geom_type == "MultiLineString":
        merged = linemerge(geom)
        if merged.geom_type == "LineString":
            return merged
        # Not mergeable into one line; just use the first part's endpoints as a fallback
        return list(geom.geoms)[0]
    return None


def _set_node_coord(G, node, coord):
    if node not in G.nodes or "x" not in G.nodes[node]:
        G.add_node(node, x=coord[0], y=coord[1])


def snap_to_nearest_node(G, x, y):
    """Return the graph node id closest to the given (x, y) point, in graph CRS units."""
    best_node, best_dist = None, float("inf")
    for n, data in G.nodes(data=True):
        if "x" not in data:
            continue
        d = (data["x"] - x) ** 2 + (data["y"] - y) ** 2
        if d < best_dist:
            best_dist, best_node = d, n
    if best_node is None:
        raise RuntimeError("No graph nodes with coordinates found; cannot snap point.")
    return best_node, best_dist ** 0.5


def transform_point(lon, lat, src_crs, dst_crs):
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    x, y = transformer.transform(lon, lat)
    return x, y


def path_edge_ids(G, node_path):
    """Given a list of nodes, return the list of edge row_indexes used (choosing the
    shortest parallel edge at each hop), plus totals for length and cd."""
    edge_ids = []
    total_length = 0.0
    total_cd = 0.0
    for a, b in zip(node_path[:-1], node_path[1:]):
        # Among parallel edges between a and b, pick the shortest one.
        parallel = G.get_edge_data(a, b)
        best_key, best_data = min(parallel.items(), key=lambda kv: kv[1]["length"])
        edge_ids.append(best_data["row_index"])
        total_length += best_data["length"]
        total_cd += best_data["cd"]
    return edge_ids, total_length, total_cd


def simplify_graph(G, weight="length"):
    """networkx's shortest_simple_paths (Yen's algorithm) doesn't support MultiGraphs.
    Build a plain Graph for path search, keeping only the cheapest parallel edge
    between any two nodes (the true multigraph edge is still looked up afterwards
    via path_edge_ids, so no attribute information is lost for the final output).
    """
    SG = nx.Graph()
    for u, v, data in G.edges(data=True):
        w = data[weight]
        if SG.has_edge(u, v):
            if w < SG[u][v][weight]:
                SG[u][v][weight] = w
        else:
            SG.add_edge(u, v, **{weight: w})
    return SG


def find_paths_within_threshold(G, source, target, percent, max_paths=50, weight="length"):
    """Yield (node_path, edge_ids, total_length, total_cd) for the shortest path and
    every subsequent simple path (Yen's algorithm order) whose length is within
    `percent`% of the shortest path length, up to `max_paths` results.
    """
    SG = simplify_graph(G, weight=weight)
    generator = nx.shortest_simple_paths(SG, source, target, weight=weight)

    results = []
    shortest_length = None
    threshold = None

    for node_path in generator:
        edge_ids, total_length, total_cd = path_edge_ids(G, node_path)

        if shortest_length is None:
            shortest_length = total_length
            threshold = shortest_length * (1 + percent / 100.0)

        if total_length > threshold:
            break

        results.append((node_path, edge_ids, total_length, total_cd))

        if len(results) >= max_paths and max_paths > 0:
            break

    return results, shortest_length, threshold


def export_paths(gdf, results, output_dir):
    """Write one .gpkg per path into output_dir, plus a summary.csv."""
    os.makedirs(output_dir, exist_ok=True)

    summary_rows = []
    for i, (node_path, edge_ids, total_length, total_cd) in enumerate(results):
        sub = gdf.loc[edge_ids].copy()
        sub["path_rank"] = i
        sub["path_order"] = range(len(sub))  # order along the path

        # --- Add path-level aggregated metrics to every row in the layer ---
        sub["total_length"] = round(total_length, 3)
        sub["total_cd"] = round(total_cd, 4)
        
        out_name = f"path_{i:03d}_len{total_length:.1f}_cd{total_cd:.3f}.gpkg"
        out_path = os.path.join(output_dir, out_name)
        sub.to_file(out_path, driver="GPKG")

        summary_rows.append({
            "path_rank": i,
            "file": out_name,
            "num_segments": len(edge_ids),
            "total_length": total_length,
            "total_cd": total_cd,
            "node_path": "-".join(str(n) for n in node_path),
        })

    import csv
    summary_path = os.path.join(output_dir, "summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    return summary_path


def run(input_gpkg, start_x, start_y, end_x, end_y, output_dir,
        percent=10.0, max_paths=50, coords_crs="EPSG:32618", clear_output=False):

    gdf, G = load_graph(input_gpkg)
    graph_crs = gdf.crs

    if str(coords_crs).upper() in ("EPSG:4326", "4326", "WGS84"):
        # start_x/start_y given as lon/lat in that case
        sx, sy = transform_point(start_x, start_y, coords_crs, graph_crs)
        ex, ey = transform_point(end_x, end_y, coords_crs, graph_crs)
    elif str(coords_crs) == str(graph_crs) or str(coords_crs).upper() in (
        str(graph_crs).upper(), str(graph_crs.to_epsg())
    ):
        # Coordinates already in the graph's native CRS (e.g. EPSG:32618) - no transform needed
        sx, sy = start_x, start_y
        ex, ey = end_x, end_y
    else:
        sx, sy = transform_point(start_x, start_y, coords_crs, graph_crs)
        ex, ey = transform_point(end_x, end_y, coords_crs, graph_crs)

    source, sdist = snap_to_nearest_node(G, sx, sy)
    target, tdist = snap_to_nearest_node(G, ex, ey)

    print(f"Start snapped to node {source} ({sdist:.1f} m away)")
    print(f"End snapped to node {target} ({tdist:.1f} m away)")

    if source == target:
        raise ValueError("Start and end snap to the same graph node; nothing to route.")

    if not nx.has_path(G, source, target):
        raise ValueError("No path exists between start and end nodes in this graph.")

    results, shortest_length, threshold = find_paths_within_threshold(
        G, source, target, percent, max_paths=max_paths
    )

    print(f"Shortest path length: {shortest_length:.2f} m")
    print(f"Threshold ({percent}% over shortest): {threshold:.2f} m")
    print(f"Found {len(results)} path(s) within threshold "
          f"(capped at max_paths={max_paths})")

    if clear_output and os.path.isdir(output_dir):
        shutil.rmtree(output_dir)

    summary_path = export_paths(gdf, results, output_dir)
    print(f"Wrote {len(results)} path gpkg file(s) and summary to: {output_dir}")
    print(f"Summary: {summary_path}")

    return results, summary_path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="Path to input .gpkg (route_MM_HH.gpkg)")
    p.add_argument("--start-x", type=float, required=True,
                   help="Start coordinate X (easting) in --coords-crs, default EPSG:32618")
    p.add_argument("--start-y", type=float, required=True,
                   help="Start coordinate Y (northing) in --coords-crs, default EPSG:32618")
    p.add_argument("--end-x", type=float, required=True,
                   help="End coordinate X (easting) in --coords-crs, default EPSG:32618")
    p.add_argument("--end-y", type=float, required=True,
                   help="End coordinate Y (northing) in --coords-crs, default EPSG:32618")
    p.add_argument("--output-dir", required=True, help="Folder to write path .gpkg files into")
    p.add_argument("--percent", type=float, default=10.0,
                   help="Include paths within this %% of the shortest path length (default 10)")
    p.add_argument("--max-paths", type=int, default=50,
                   help="Safety cap on number of near-shortest paths to generate (default 50)")
    p.add_argument("--coords-crs", default="EPSG:32618",
                   help="CRS of the input start/end coordinates. Default EPSG:32618 (UTM 18N, "
                        "matches the graph's native CRS - pass EPSG:4326 to use lon/lat instead, "
                        "in which case --start-x/--end-x are longitude and --start-y/--end-y are latitude)")
    p.add_argument("--clear-output", action="store_true",
                   help="Delete output-dir first if it already exists")
    args = p.parse_args()

    run(
        input_gpkg=args.input,
        start_x=args.start_x,
        start_y=args.start_y,
        end_x=args.end_x,
        end_y=args.end_y,
        output_dir=args.output_dir,
        percent=args.percent,
        max_paths=args.max_paths,
        coords_crs=args.coords_crs,
        clear_output=args.clear_output,
    )


if __name__ == "__main__":
    main()
