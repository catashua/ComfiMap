"""Find shorter and cooler walks on the Financial District pedestrian network."""

from __future__ import annotations

import heapq
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import networkx as nx
from pyproj import Transformer
from shapely.ops import linemerge

GRAPH_DIR = (
    Path(__file__).resolve().parent
    / "data"
    / "Biobjective results analysis (7-27)"
    / "weighted graph"
)

TO_UTM = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True)
TO_LONLAT = Transformer.from_crs("EPSG:32618", "EPSG:4326", always_xy=True)

# A route may be up to 20% longer than the shortest walk.
STRETCH = 1.20
# Drop a route that is almost the same as one already kept.
MIN_EXTRA_METERS = 10.0
MIN_HEAT_CHANGE = 0.02
MAX_ROUTES = 12
MAX_SNAP_METERS = 300.0
EPS = 1e-4


class RouteError(Exception):
    """A problem we can explain to the person using the site."""


def list_graphs():
    """Return {(month, hour): path} for every route_MM_HH.gpkg file."""
    found = {}
    if not GRAPH_DIR.is_dir():
        return found
    for path in GRAPH_DIR.glob("route_*.gpkg"):
        parts = path.stem.split("_")
        if len(parts) != 3:
            continue
        _, month, hour = parts
        if month.isdigit() and hour.isdigit():
            found[(int(month), int(hour))] = path
    return found


def _endpoints(geom):
    if geom.geom_type == "LineString":
        coords = list(geom.coords)
        return coords[0], coords[-1]
    if geom.geom_type == "MultiLineString":
        merged = linemerge(geom)
        if merged.geom_type == "LineString":
            coords = list(merged.coords)
            return coords[0], coords[-1]
        parts = list(geom.geoms)
        return list(parts[0].coords)[0], list(parts[-1].coords)[-1]
    raise RouteError(f"Unexpected street shape: {geom.geom_type}")


def load_network(path):
    """Build an undirected walking graph. Edge cost is length plus heat (`cd`)."""
    edges = gpd.read_file(path)
    graph = nx.Graph()
    for _, row in edges.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        start, end = _endpoints(geom)
        u = (round(start[0], 2), round(start[1], 2))
        v = (round(end[0], 2), round(end[1], 2))
        if u == v:
            continue
        length = float(row["Shape_Leng"])
        heat = float(row["cd"])
        if graph.has_edge(u, v):
            if length < graph[u][v]["length"]:
                graph[u][v]["length"] = length
                graph[u][v]["cd"] = heat
                graph[u][v]["geom"] = geom
        else:
            graph.add_edge(u, v, length=length, cd=heat, geom=geom)
    return graph


def geocode(query):
    """Turn an address into longitude, latitude using OpenStreetMap Nominatim."""
    text = query.strip()
    if not text:
        raise RouteError("Type both a starting address and a destination.")
    if "new york" not in text.lower():
        text = f"{text}, New York, NY"
    params = urllib.parse.urlencode({"q": text, "format": "json", "limit": 1})
    request = urllib.request.Request(
        "https://nominatim.openstreetmap.org/search?" + params,
        headers={"User-Agent": "ComfiMap/1.0 (student walking-route project)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except Exception as exc:
        raise RouteError(
            "The address search did not answer. Check your internet connection and try again."
        ) from exc
    if not payload:
        raise RouteError(f"Could not find “{query.strip()}”. Try a fuller street address.")
    hit = payload[0]
    return float(hit["lon"]), float(hit["lat"]), hit.get("display_name", text)


def snap(graph, lon, lat):
    """Move a longitude/latitude onto the nearest corner in the walking network."""
    x, y = TO_UTM.transform(lon, lat)
    best = None
    best_d2 = MAX_SNAP_METERS ** 2
    for node in graph.nodes:
        d2 = (node[0] - x) ** 2 + (node[1] - y) ** 2
        if d2 < best_d2:
            best = node
            best_d2 = d2
    if best is None:
        raise RouteError(
            "That address is outside the Financial District map this site knows about."
        )
    return best


@dataclass
class _Label:
    dist: float
    cd: float
    node: tuple
    prev: int | None


# Keep one walk in each 10 m band so the search stays fast enough for a website.
# The true shortest arrival at each corner is always kept as well.
BUCKET_M = 10.0


def _pareto_paths(graph, source, target, budget):
    labels: list[_Label] = []
    # node -> list of (bucket, label index), sorted by bucket. Bucket -1 is shortest.
    alive: dict = defaultdict(list)
    heap = []
    tie = 0
    heapq.heappush(heap, (0.0, 0.0, tie, source, None))

    while heap:
        dist, cd, _, node, prev = heapq.heappop(heap)
        if dist > budget + EPS:
            continue
        front = alive[node]
        bucket = -1 if not front else int(dist // BUCKET_M)
        skip = False
        for old_bucket, index in front:
            if old_bucket > bucket:
                break
            if labels[index].cd <= cd + EPS:
                skip = True
                break
        if skip:
            continue
        new_index = len(labels)
        labels.append(_Label(dist, cd, node, prev))
        updated = [
            (b, i)
            for b, i in front
            if b != bucket and not (b > bucket and labels[i].cd >= cd - EPS)
        ]
        updated.append((bucket, new_index))
        updated.sort()
        alive[node] = updated
        if node == target:
            continue
        for neighbor in graph.neighbors(node):
            edge = graph[node][neighbor]
            new_dist = dist + edge["length"]
            if new_dist > budget + EPS:
                continue
            tie += 1
            heapq.heappush(
                heap,
                (new_dist, cd + edge["cd"], tie, neighbor, new_index),
            )

    routes = []
    for _bucket, index in alive[target]:
        nodes = []
        cursor = index
        seen = set()
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            nodes.append(labels[cursor].node)
            cursor = labels[cursor].prev
        nodes.reverse()
        lab = labels[index]
        routes.append({"distance_m": lab.dist, "heat": lab.cd, "nodes": nodes})
    routes.sort(key=lambda item: (item["distance_m"], item["heat"]))
    return routes


def _thin(routes):
    """Keep a short list of clearly different walks, shortest first and coolest last."""
    if not routes:
        return []
    kept = [routes[0]]
    for route in routes[1:]:
        previous = kept[-1]
        extra = route["distance_m"] - previous["distance_m"]
        heat_drop = (previous["heat"] - route["heat"]) / max(previous["heat"], 1.0)
        if extra < MIN_EXTRA_METERS and heat_drop < MIN_HEAT_CHANGE:
            continue
        kept.append(route)
    if routes[-1]["heat"] < kept[-1]["heat"] - EPS:
        kept.append(routes[-1])
    if len(kept) <= MAX_ROUTES:
        return kept
    last = len(kept) - 1
    picks = sorted({round(i * last / (MAX_ROUTES - 1)) for i in range(MAX_ROUTES)})
    return [kept[i] for i in picks]


def _as_lines(geom):
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    if geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        pieces = []
        for part in geom.geoms:
            pieces.extend(_as_lines(part))
        return pieces
    return []


def _line_latlon(graph, nodes):
    parts = []
    for a, b in zip(nodes[:-1], nodes[1:]):
        parts.extend(_as_lines(graph[a][b]["geom"]))
    if not parts:
        return []
    lines = []
    for piece in _as_lines(linemerge(parts)):
        lines.append(
            [
                [lat, lon]
                for lon, lat in (TO_LONLAT.transform(x, y) for x, y in piece.coords)
            ]
        )
    return lines


def routes_between(graph, origin_lonlat, dest_lonlat):
    """Return the Pareto walks from origin to destination, shortest first."""
    start = snap(graph, *origin_lonlat)
    end = snap(graph, *dest_lonlat)
    if start == end:
        raise RouteError("Those two addresses land on the same corner. Try a farther destination.")
    try:
        shortest = nx.shortest_path_length(graph, start, end, weight="length")
    except nx.NetworkXNoPath as exc:
        raise RouteError("No walking connection was found between those two corners.") from exc
    found = _pareto_paths(graph, start, end, shortest * STRETCH)
    found = _thin(found)
    if not found:
        raise RouteError("No walk was found inside the distance limit.")
    shortest_heat = found[0]["heat"]
    results = []
    for route in found:
        extra = route["distance_m"] - found[0]["distance_m"]
        heat_saved = shortest_heat - route["heat"]
        results.append(
            {
                "distance_m": route["distance_m"],
                "extra_m": extra,
                "minutes": route["distance_m"] / 80.0,
                "heat": route["heat"],
                "heat_saved_pct": (100.0 * heat_saved / shortest_heat) if shortest_heat else 0.0,
                "lines": _line_latlon(graph, route["nodes"]),
            }
        )
    return results


def knee_index(routes):
    """Pick the walk closest to “short and cool” on this frontier."""
    if len(routes) < 2:
        return 0
    distances = [route["distance_m"] for route in routes]
    heats = [route["heat"] for route in routes]
    d0, d1 = min(distances), max(distances)
    h0, h1 = min(heats), max(heats)
    best_i = 0
    best_score = None
    for i, route in enumerate(routes):
        dn = 0.0 if d1 == d0 else (route["distance_m"] - d0) / (d1 - d0)
        hn = 0.0 if h1 == h0 else (route["heat"] - h0) / (h1 - h0)
        score = dn * dn + hn * hn
        if best_score is None or score < best_score:
            best_score = score
            best_i = i
    return best_i
