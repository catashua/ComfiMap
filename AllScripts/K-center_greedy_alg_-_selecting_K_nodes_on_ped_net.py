
import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

# ---------- CONFIG ----------
GPKG_PATH = r"C:\Users\Student\Downloads\fidi_pedestrian_network_osm_no-dead-ends_no-pier_edges.gpkg"
LAYER = None
K = 80
SNAP_DECIMALS = 3
RANDOM_SEED = 0
LOCAL_SEARCH_ITERS = 200
# -----------------------------

np.random.seed(RANDOM_SEED)

gdf = gpd.read_file(GPKG_PATH, layer=LAYER)

def node_key(pt):
    return (round(pt[0], SNAP_DECIMALS), round(pt[1], SNAP_DECIMALS))

def get_parts(geom):
    """Return list of LineString parts for a Line or MultiLine geometry."""
    if geom is None:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    elif geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    return []

G = nx.Graph()
edge_count = 0
for _, row in gdf.iterrows():
    parts = get_parts(row.geometry)
    if not parts:
        continue
    # split Shape_Leng proportionally across parts by their actual length,
    # since Shape_Leng is stored per-feature not per-part
    total_len = sum(p.length for p in parts) or 1.0
    shape_leng = row.get("Shape_Leng", None)

    for part in parts:
        coords = list(part.coords)
        u = node_key(coords[0])
        v = node_key(coords[-1])
        part_len = part.length
        if shape_leng and shape_leng > 0:
            w = shape_leng * (part_len / total_len)
        else:
            w = part_len
        if w <= 0:
            continue
        if G.has_edge(u, v):
            G[u][v]["weight"] = min(G[u][v]["weight"], w)
        else:
            G.add_edge(u, v, weight=w)
            edge_count += 1

print(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

if G.number_of_nodes() == 0:
    raise RuntimeError("Still 0 nodes — check field names / geometry column.")

if not nx.is_connected(G):
    comps = sorted(nx.connected_components(G), key=len, reverse=True)
    print(f"WARNING: {len(comps)} components. Using largest ({len(comps[0])} nodes, "
          f"dropping {G.number_of_nodes()-len(comps[0])}).")
    G = G.subgraph(comps[0]).copy()

nodes = list(G.nodes())
idx = {n: i for i, n in enumerate(nodes)}
N = len(nodes)

rows, cols, data = [], [], []
for u, v, w in G.edges(data="weight"):
    i, j = idx[u], idx[v]
    rows += [i, j]; cols += [j, i]; data += [w, w]
A = csr_matrix((data, (rows, cols)), shape=(N, N))

print("Computing all-pairs shortest paths...")
D = dijkstra(A, directed=False)

def greedy_p_center(D, k):
    N = D.shape[0]
    facilities = [np.random.randint(N)]
    min_dist = D[facilities[0]].copy()
    for _ in range(k - 1):
        next_node = int(np.argmax(min_dist))
        facilities.append(next_node)
        min_dist = np.minimum(min_dist, D[next_node])
    return facilities, min_dist.max()

facilities, radius = greedy_p_center(D, K)
print(f"Greedy solution radius: {radius:.2f}")

def evaluate(facility_idxs, D):
    return D[facility_idxs, :].min(axis=0).max()

if LOCAL_SEARCH_ITERS > 0:
    best_facilities = list(facilities)
    best_radius = evaluate(best_facilities, D)
    it = 0
    for it in range(LOCAL_SEARCH_ITERS):
        improved = False
        cur_min = D[best_facilities, :].min(axis=0)
        bottleneck_node = int(np.argmax(cur_min))
        for f_pos in range(len(best_facilities)):
            trial = best_facilities.copy()
            trial[f_pos] = bottleneck_node
            r = evaluate(trial, D)
            if r < best_radius:
                best_facilities = trial
                best_radius = r
                improved = True
                break
        if not improved:
            break
    facilities, radius = best_facilities, best_radius
    print(f"After local search, radius: {radius:.2f} (iterations used: {it+1})")

chosen_nodes = [nodes[i] for i in facilities]
print("\nSelected node coordinates (x, y):")
for c in chosen_nodes:
    print(c)

out = gpd.GeoDataFrame(
    {"radius": [radius]*len(chosen_nodes)},
    geometry=gpd.points_from_xy([c[0] for c in chosen_nodes], [c[1] for c in chosen_nodes]),
    crs=gdf.crs
)
out.to_file(r"C:\Users\Student\Downloads\p_center_nodes.gpkg", driver="GPKG")
print("\nSaved to p_center_nodes.gpkg")


