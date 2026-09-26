"""
Coolest-path trade-off analysis between nearby center nodes.
BATCH VERSION: runs the same analysis for every route_MM_HH.gpkg file in a folder,
writing one CSV per input file.

Pipeline (per edge file):
1. Load pedestrian graph (edges w/ Shape_Leng, cd) -> undirected networkx graph.
2. Load 85 center nodes, snap each to nearest graph node.
3. For every pair of center nodes, find shortest-DISTANCE path (Dijkstra on Shape_Leng).
   Keep pairs with shortest distance <= 200m.
4. For each kept pair, find the "coolest" path: minimum total cd among all paths
   whose distance is <= 1.1 * shortest distance, via bicriteria (Pareto) label-setting search.
5. Compute m = (dist_cool - dist_short) / (cd_short - cd_cool) for every pair
   (no filtering — matches the version you ran successfully in QGIS).
"""

import os
import glob
import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import heapq
from collections import defaultdict
from shapely.ops import linemerge

# ---------------- CONFIG ----------------
EDGES_FOLDER = r"C:\Users\Student\Downloads\weighted graph"
EDGES_PATTERN = os.path.join(EDGES_FOLDER, "route_*.gpkg")
CENTERS_PATH = r"C:\Users\Student\Downloads\85_optimal_100m.gpkg"
OUTPUT_FOLDER = os.path.join(r"C:\Users\Student\Downloads\tradeoff_outputs")
DIST_THRESHOLD = 200.0
SLACK_FACTOR = 1.1


def get_endpoints(geom):
    if geom.geom_type == "LineString":
        coords = list(geom.coords)
        return coords[0], coords[-1]
    if geom.geom_type == "MultiLineString":
        merged = linemerge(geom)
        if merged.geom_type == "LineString":
            coords = list(merged.coords)
            return coords[0], coords[-1]
        parts = list(geom.geoms)
        start = list(parts[0].coords)[0]
        end = list(parts[-1].coords)[-1]
        return start, end
    raise ValueError(f"Unexpected geometry type: {geom.geom_type}")


def build_graph(edges_path):
    edges = gpd.read_file(edges_path)
    G = nx.Graph()
    for _, row in edges.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        start, end = get_endpoints(geom)
        u = (round(start[0], 2), round(start[1], 2))
        v = (round(end[0], 2), round(end[1], 2))
        length = float(row["Shape_Leng"])
        cd = float(row["cd"])
        if G.has_edge(u, v):
            if length < G[u][v]["length"]:
                G[u][v]["length"] = length
                G[u][v]["cd"] = cd
        else:
            G.add_edge(u, v, length=length, cd=cd)
    return G


def snap_centers(centers_path, G):
    centers = gpd.read_file(centers_path)
    node_ids = list(G.nodes)
    node_pts = gpd.GeoSeries(gpd.points_from_xy(
        [n[0] for n in node_ids], [n[1] for n in node_ids]
    ), crs=centers.crs)
    node_gdf = gpd.GeoDataFrame({"node": node_ids}, geometry=node_pts, crs=centers.crs)

    snapped = gpd.sjoin_nearest(
        centers.reset_index().rename(columns={"index": "center_id"}),
        node_gdf,
        how="left",
        distance_col="snap_dist",
    )
    snapped = snapped.drop_duplicates(subset="center_id")
    return dict(zip(snapped["center_id"], snapped["node"]))


def shortest_distance_pairs(G, center_nodes, cutoff=DIST_THRESHOLD):
    results = {}
    ids = list(center_nodes.keys())
    for cid in ids:
        src = center_nodes[cid]
        dist, paths = nx.single_source_dijkstra(G, src, cutoff=cutoff, weight="length")
        for other_id in ids:
            if other_id == cid:
                continue
            tgt = center_nodes[other_id]
            if tgt in dist:
                key = tuple(sorted((cid, other_id)))
                d = dist[tgt]
                if key not in results or d < results[key][0]:
                    results[key] = (d, paths[tgt])
    return results


def path_cd(G, path_nodes):
    return sum(G[u][v]["cd"] for u, v in zip(path_nodes[:-1], path_nodes[1:]))


def pareto_min_cd_within_budget(G, source, target, budget):
    frontier = [(0.0, 0.0, source)]
    labels = defaultdict(list)
    best_at_target = None

    while frontier:
        length, cd, node = heapq.heappop(frontier)
        if length > budget:
            continue

        dominated = False
        for L, C in labels[node]:
            if L <= length and C <= cd:
                dominated = True
                break
        if dominated:
            continue
        labels[node] = [(L, C) for (L, C) in labels[node] if not (length <= L and cd <= C)]
        labels[node].append((length, cd))

        if node == target:
            if best_at_target is None or cd < best_at_target[0]:
                best_at_target = (cd, length)
            continue

        for nbr in G.neighbors(node):
            e = G[node][nbr]
            new_length = length + e["length"]
            new_cd = cd + e["cd"]
            if new_length > budget:
                continue
            heapq.heappush(frontier, (new_length, new_cd, nbr))

    if best_at_target is None:
        return None, None
    return best_at_target


def process_file(edges_path, centers_path, output_folder):
    fname = os.path.splitext(os.path.basename(edges_path))[0]  # e.g. route_07_14
    print(f"\n=== Processing {fname} ===")

    G = build_graph(edges_path)
    centers = snap_centers(centers_path, G)

    pairs = shortest_distance_pairs(G, centers, cutoff=DIST_THRESHOLD)
    print(f"  Pairs within {DIST_THRESHOLD}m: {len(pairs)}")

    detail_rows = []
    for (id_a, id_b), (d_short, path_short) in pairs.items():
        src, tgt = centers[id_a], centers[id_b]
        cd_short = path_cd(G, path_short)
        budget = d_short * SLACK_FACTOR

        cd_cool, d_cool = pareto_min_cd_within_budget(G, src, tgt, budget)
        if cd_cool is None:
            continue

        delta_cd = cd_short - cd_cool
        delta_dist = d_cool - d_short
        m = delta_dist / delta_cd if delta_cd > 0 else np.nan

        detail_rows.append({
            "center_a": id_a, "center_b": id_b,
            "d_short": d_short, "cd_short": cd_short,
            "d_cool": d_cool, "cd_cool": cd_cool,
            "delta_dist": delta_dist, "delta_cd": delta_cd, "m": m,
        })

    df = pd.DataFrame(detail_rows)
    os.makedirs(output_folder, exist_ok=True)
    out_path = os.path.join(output_folder, f"{fname}_tradeoffs.csv")
    df.to_csv(out_path, index=False)
    print(f"  Wrote {len(df)} rows to {out_path}")
    return out_path


def main():
    edge_files = sorted(glob.glob(EDGES_PATTERN))
    print(f"Found {len(edge_files)} edge files matching pattern.")
    if not edge_files:
        print(f"No files found matching {EDGES_PATTERN} — check EDGES_FOLDER/pattern.")
        return

    written = []
    for edges_path in edge_files:
        try:
            out_path = process_file(edges_path, CENTERS_PATH, OUTPUT_FOLDER)
            written.append(out_path)
        except Exception as ex:
            print(f"  !! FAILED on {edges_path}: {ex}")

    print(f"\nDone. Wrote {len(written)} CSVs to {OUTPUT_FOLDER}")


main()
