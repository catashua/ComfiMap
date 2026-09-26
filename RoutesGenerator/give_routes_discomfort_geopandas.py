#!/usr/bin/env python3
"""
Alternative-route "discomfort" enumerator, GeoPandas edition.

Given a start and end coordinate on a line-network GeoPackage layer, finds
every simple path whose total distance is within `stretch_factor` x the
shortest possible distance, tracking a secondary "discomfort" metric along
each one. Each surviving alternative route is written out as its own
GeoPackage file.

Fixes vs. the original QGIS console script:
  1. Segment splitting now operates on a live "registry" of current
     sub-segments rather than always re-reading each feature's original,
     un-split geometry/attributes. This fixes a real bug in the original:
     if the start and end points both snap onto the same original line
     feature, the second split silently corrupted lengths/discomfort and
     produced overlapping duplicate edges.
  2. The exhaustive DFS is now pruned using a memoized "shortest remaining
     distance to the destination" table, computed once via a single
     Dijkstra pass from the end node. Any branch that can't possibly reach
     the destination within budget -- even in the best case -- is cut
     immediately, instead of being explored step by step until it
     eventually exceeds the budget. This is the main fix for combinatorial
     blow-up on real street networks.
  3. The DFS is iterative with explicit backtracking (mutate + undo)
     instead of copying the visited-set and path-history list on every
     single branch, and it has no Python recursion-depth limit.
  4. Multipart (MultiLineString) features are exploded into individual
     segments instead of silently using only their first part.

Usage (CLI):
    python give_routes_discomfort_geopandas.py input.gpkg output_folder \
        --input-layer network \
        --start 582933.54 4507092.79 \
        --end   583459.91 4507239.99 \
        --stretch-factor 1.1 \
        --time-stamp 18 \
        --length-field ped_length \
        --discomfort-field weighted_discomfort

Or import and call `find_alternative_discomfort_routes(...)` directly.
"""

import argparse
import heapq
import itertools
import math
import os

import geopandas as gpd
from shapely.geometry import LineString, Point


# ==============================================================================
# GRAPH + SEGMENT REGISTRY CONSTRUCTION
# ==============================================================================

def _round_pt(x, y):
    return (round(x, 4), round(y, 4))


def _safe_float(row, field, default):
    """Read a numeric field from a GeoDataFrame row, falling back on failure/NaN."""
    if field not in row.index:
        return default
    val = row[field]
    if val is None:
        return default
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    if math.isnan(f):
        return default
    return f


def add_edge(graph, pt1, pt2, dist, discomfort, origin_fid, polyline_pts, record_id):
    """Add an undirected edge. `record_id` uniquely identifies this specific
    edge instance so it can be precisely removed later, even if another edge
    happens to share the same endpoints."""
    u = _round_pt(*pt1)
    v = _round_pt(*pt2)
    if u == v:
        return
    graph.setdefault(u, []).append((v, dist, discomfort, origin_fid, polyline_pts, record_id))
    graph.setdefault(v, []).append((u, dist, discomfort, origin_fid, polyline_pts, record_id))


def remove_edge_by_record(graph, pt1, pt2, record_id):
    u = _round_pt(*pt1)
    v = _round_pt(*pt2)
    if u in graph:
        graph[u] = [e for e in graph[u] if e[5] != record_id]
    if v in graph:
        graph[v] = [e for e in graph[v] if e[5] != record_id]


def build_graph_and_registry(gdf, length_field, discomfort_field):
    """
    Builds the base graph plus a `registry`: for every original feature (or
    part of a multipart feature), a list of the "live" sub-segments
    currently represented in the graph. Initially each feature has exactly
    one live sub-segment (itself); splitting replaces one live sub-segment
    with two.
    """
    graph = {}
    registry = {}
    record_counter = itertools.count()

    for idx, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue

        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        multipart = len(lines) > 1

        for part_i, line in enumerate(lines):
            coords = list(line.coords)
            if len(coords) < 2:
                continue

            length = _safe_float(row, length_field, default=line.length)
            discomfort = _safe_float(row, discomfort_field, default=0.0)
            seg_id = (idx, part_i) if multipart else idx
            rid = next(record_counter)

            add_edge(graph, coords[0], coords[-1], length, discomfort, idx, coords, rid)
            registry[seg_id] = [{
                "coords": coords,
                "length": length,
                "discomfort": discomfort,
                "origin_fid": idx,
                "record_id": rid,
            }]

    return graph, registry, record_counter


# ==============================================================================
# DYNAMIC MID-SEGMENT SPLITTING (registry-aware)
# ==============================================================================

def _find_nearest_live_record(registry, target_pt):
    """Scan every currently-live sub-segment and return the closest one."""
    best = None
    best_dist = float("inf")
    for seg_id, records in registry.items():
        for rec_idx, rec in enumerate(records):
            line = LineString(rec["coords"])
            d = line.distance(target_pt)
            if d < best_dist:
                best_dist = d
                best = (seg_id, rec_idx, line)
    return best


def split_network_at_point(registry, graph, target_pt, record_counter):
    """
    Snap `target_pt` onto the nearest *currently live* sub-segment, split it,
    and update both `graph` and `registry` in place. Returns the rounded
    node key for the snap point. If the snap point lands exactly on an
    existing endpoint, no split occurs and that endpoint's key is returned.
    """
    found = _find_nearest_live_record(registry, target_pt)
    if found is None:
        raise RuntimeError("No network segments available to snap to.")

    seg_id, rec_idx, line = found
    rec = registry[seg_id][rec_idx]
    coords = rec["coords"]

    proj_dist = line.project(target_pt)
    snapped_point = line.interpolate(proj_dist)
    snap_xy = (snapped_point.x, snapped_point.y)
    node_key = _round_pt(*snap_xy)

    start_key = _round_pt(*coords[0])
    end_key = _round_pt(*coords[-1])

    if node_key == start_key:
        return start_key
    if node_key == end_key:
        return end_key

    total_len = rec["length"]
    total_discomfort = rec["discomfort"]
    origin_fid = rec["origin_fid"]

    insert_idx = 1
    for i in range(len(coords) - 1):
        d0 = line.project(Point(coords[i]))
        d1 = line.project(Point(coords[i + 1]))
        if d0 <= proj_dist <= d1:
            insert_idx = i + 1
            break

    pts_part1 = coords[:insert_idx] + [snap_xy]
    pts_part2 = [snap_xy] + coords[insert_idx:]

    geom_len1 = LineString(pts_part1).length if len(pts_part1) > 1 else 0.0
    geom_len2 = LineString(pts_part2).length if len(pts_part2) > 1 else 0.0
    geom_total = (geom_len1 + geom_len2) or 1.0

    len1 = (geom_len1 / geom_total) * total_len
    len2 = (geom_len2 / geom_total) * total_len
    disc1 = (geom_len1 / geom_total) * total_discomfort
    disc2 = (geom_len2 / geom_total) * total_discomfort

    # Remove the stale live edge and replace it with its two sub-segments.
    remove_edge_by_record(graph, coords[0], coords[-1], rec["record_id"])

    rid1 = next(record_counter)
    rid2 = next(record_counter)
    add_edge(graph, coords[0], snap_xy, len1, disc1, origin_fid, pts_part1, rid1)
    add_edge(graph, snap_xy, coords[-1], len2, disc2, origin_fid, pts_part2, rid2)

    registry[seg_id] = (
        registry[seg_id][:rec_idx]
        + [
            {"coords": pts_part1, "length": len1, "discomfort": disc1,
             "origin_fid": origin_fid, "record_id": rid1},
            {"coords": pts_part2, "length": len2, "discomfort": disc2,
             "origin_fid": origin_fid, "record_id": rid2},
        ]
        + registry[seg_id][rec_idx + 1:]
    )

    return node_key


# ==============================================================================
# DIJKSTRA (also serves as the memoized distance-to-target pruning table)
# ==============================================================================

def compute_dist_to_target(graph, target_node):
    """Single-source shortest distances from `target_node` to every reachable
    node, computed once and reused both as the baseline shortest-path length
    and as the pruning heuristic for the DFS below."""
    dist = {target_node: 0.0}
    pq = [(0.0, target_node)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for v, w, _disc, _fid, _pts, _rid in graph.get(u, []):
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                heapq.heappush(pq, (nd, v))
    return dist


# ==============================================================================
# EXHAUSTIVE (BUT PRUNED) PATH ENUMERATION
# ==============================================================================

def find_alternative_paths(graph, start_node, end_node, max_allowed_length, dist_to_end):
    """
    Iteratively enumerates every simple path from start_node to end_node
    whose total length is <= max_allowed_length, pruning any branch whose
    best-case remaining distance (from the memoized `dist_to_end` table)
    can't possibly finish within budget.

    Returns a list of (total_dist, total_discomfort, [(fid, seg_len, seg_discomfort, pts), ...]).
    """
    all_paths = []

    if start_node == end_node:
        return all_paths

    node_stack = [start_node]
    iter_stack = [iter(graph.get(start_node, []))]
    dist_stack = [0.0]
    discomfort_stack = [0.0]
    edge_history = []
    visited = {start_node}

    while node_stack:
        try:
            neighbor, edge_len, edge_discomfort, fid, pts, _rid = next(iter_stack[-1])
        except StopIteration:
            finished_node = node_stack.pop()
            iter_stack.pop()
            dist_stack.pop()
            discomfort_stack.pop()
            if edge_history:
                edge_history.pop()
            visited.discard(finished_node)
            continue

        if neighbor in visited:
            continue

        next_dist = dist_stack[-1] + edge_len
        if next_dist > max_allowed_length:
            continue

        if neighbor == end_node:
            all_paths.append((
                next_dist,
                discomfort_stack[-1] + edge_discomfort,
                edge_history + [(fid, edge_len, edge_discomfort, pts)],
            ))
            continue

        # Memoized pruning: even in the best case, can this branch still finish in budget?
        remaining = dist_to_end.get(neighbor, float("inf"))
        if remaining == float("inf") or next_dist + remaining > max_allowed_length:
            continue

        node_stack.append(neighbor)
        iter_stack.append(iter(graph.get(neighbor, [])))
        dist_stack.append(next_dist)
        discomfort_stack.append(discomfort_stack[-1] + edge_discomfort)
        edge_history.append((fid, edge_len, edge_discomfort, pts))
        visited.add(neighbor)

    return all_paths


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

def find_alternative_discomfort_routes(
    input_gpkg,
    output_dir,
    start_coord,
    end_coord,
    input_layer=None,
    stretch_factor=1.1,
    time_stamp=None,
    length_field="ped_length",
    discomfort_field="weighted_discomfort",
):
    """
    Loads `input_layer` from `input_gpkg`, finds every simple path between
    `start_coord` and `end_coord` (tuples of (x, y) in the layer's CRS)
    within `stretch_factor` x the shortest possible distance, and writes
    each one to its own GeoPackage file inside `output_dir`.

    `time_stamp` is purely a label (e.g. an hour-of-day) used in output
    filenames/layer names; pass None to omit it.

    Returns a list of (total_dist, total_discomfort, output_path) tuples,
    sorted by total_discomfort ascending (most comfortable alternative first).
    """
    print(f"Loading network from: {input_gpkg} (layer={input_layer or 'default'})")
    gdf = gpd.read_file(input_gpkg, layer=input_layer)

    if gdf.empty:
        raise RuntimeError("Input layer is empty.")

    label = f" (AP {time_stamp})" if time_stamp is not None else ""
    print(f"Building graph{label}...")
    graph, registry, record_counter = build_graph_and_registry(gdf, length_field, discomfort_field)

    start_pt = Point(start_coord)
    end_pt = Point(end_coord)

    print("Snapping and splitting network at start point...")
    start_node = split_network_at_point(registry, graph, start_pt, record_counter)
    print("Snapping and splitting network at end point...")
    end_node = split_network_at_point(registry, graph, end_pt, record_counter)

    if start_node == end_node:
        raise ValueError("Start and end points snapped to the same network node.")

    print("Computing baseline shortest distance (also used as the pruning memo table)...")
    dist_to_end = compute_dist_to_target(graph, end_node)

    shortest_possible_length = dist_to_end.get(start_node, float("inf"))
    if shortest_possible_length == float("inf"):
        raise ValueError("No physical path connection found between start and end nodes.")

    max_allowed_length = shortest_possible_length * stretch_factor

    print("\n" + "=" * 60)
    print(f"Baseline shortest route: {shortest_possible_length:.2f} meters")
    print(f"Maximum route distance threshold ({stretch_factor}x): {max_allowed_length:.2f} meters")
    print("=" * 60)

    print("Enumerating alternative routes (pruned DFS)...")
    all_paths_data = find_alternative_paths(graph, start_node, end_node, max_allowed_length, dist_to_end)

    total_paths = len(all_paths_data)
    if total_paths == 0:
        print("No alternative paths met the criteria within the threshold boundary.")
        return []

    # Most comfortable route first.
    all_paths_data.sort(key=lambda p: (p[1], p[0]))

    print(f"Found {total_paths} valid paths. Writing GeoPackage exports...")
    os.makedirs(output_dir, exist_ok=True)

    results = []
    for idx, (total_dist, total_discomfort, history) in enumerate(all_paths_data, start=1):
        records = []
        for fid, seg_len, seg_discomfort, pts in history:
            records.append({
                "segment_id": str(fid),
                length_field: seg_len,
                discomfort_field: seg_discomfort,
                "total_dist": total_dist,
                "total_discomfort": total_discomfort,
                "geometry": LineString(pts),
            })

        out_gdf = gpd.GeoDataFrame(records, geometry="geometry", crs=gdf.crs)

        filename = f"Alternative_Route_{idx}.gpkg"
        out_path = os.path.join(output_dir, filename)
        layer_name = f"Route_{idx}" + (f"_AP_{time_stamp}" if time_stamp is not None else "")

        out_gdf.to_file(out_path, layer=layer_name, driver="GPKG")
        results.append((total_dist, total_discomfort, out_path))

    print(f"\nGenerated {total_paths} standalone GeoPackage files inside:\n{output_dir}")
    return results


def _parse_args():
    parser = argparse.ArgumentParser(description="Alternative discomfort-tracking routes via GeoPandas + pruned DFS.")
    parser.add_argument("input_gpkg", help="Path to the input GeoPackage.")
    parser.add_argument("output_dir", help="Folder to write the alternative-route GeoPackages into.")
    parser.add_argument("--input-layer", default=None, help="Layer name in the input GeoPackage (default: first layer).")
    parser.add_argument("--start", nargs=2, type=float, required=True, metavar=("X", "Y"), help="Start coordinate.")
    parser.add_argument("--end", nargs=2, type=float, required=True, metavar=("X", "Y"), help="End coordinate.")
    parser.add_argument("--stretch-factor", type=float, default=1.1, help="Max allowed distance as a multiple of the shortest route (default: 1.1).")
    parser.add_argument("--time-stamp", default=None, help="Optional label (e.g. hour of day) used in output names.")
    parser.add_argument("--length-field", default="ped_length", help="Field holding segment length (default: ped_length).")
    parser.add_argument("--discomfort-field", default="weighted_discomfort", help="Field holding discomfort value (default: weighted_discomfort).")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    find_alternative_discomfort_routes(
        input_gpkg=args.input_gpkg,
        output_dir=args.output_dir,
        start_coord=tuple(args.start),
        end_coord=tuple(args.end),
        input_layer=args.input_layer,
        stretch_factor=args.stretch_factor,
        time_stamp=args.time_stamp,
        length_field=args.length_field,
        discomfort_field=args.discomfort_field,
    )
