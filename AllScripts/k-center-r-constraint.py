import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
import pulp
import time

# ---------- CONFIG ----------
GPKG_PATH = r"C:\Users\Student\Downloads\fidi_pedestrian_network_osm_no-dead-ends-pier.gpkg"
LAYER = "fidi_pedestrian_network_osm_nodeadendspier"
THRESHOLD = 100.0   # meters
SNAP_DECIMALS = 3
SOLVER_TIME_LIMIT = 600  # seconds
# -----------------------------

total_start = time.time()

gdf = gpd.read_file(GPKG_PATH, layer=LAYER)

def node_key(pt):
    return (round(pt[0], SNAP_DECIMALS), round(pt[1], SNAP_DECIMALS))

def get_parts(geom):
    if geom is None:
        return []
    if geom.geom_type == "LineString":
        return [geom]
    elif geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    return []

# ---- Build graph ----
build_start = time.time()
G = nx.Graph()
for _, row in gdf.iterrows():
    parts = get_parts(row.geometry)
    if not parts:
        continue
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

print(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges "
      f"({time.time()-build_start:.2f} s)")

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

# ---- All-pairs shortest paths ----
dijkstra_start = time.time()
rows, cols, data = [], [], []
for u, v, w in G.edges(data="weight"):
    i, j = idx[u], idx[v]
    rows += [i, j]; cols += [j, i]; data += [w, w]
A = csr_matrix((data, (rows, cols)), shape=(N, N))

print("Computing all-pairs shortest paths...")
D = dijkstra(A, directed=False)
print(f"Dijkstra completed ({time.time()-dijkstra_start:.2f} s)")

# ---- Exact ILP min dominating set ----
ilp_start = time.time()
prob = pulp.LpProblem("min_dominating_set", pulp.LpMinimize)
x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(N)]
prob += pulp.lpSum(x)

for j in range(N):
    covering_facilities = np.where(D[:, j] <= THRESHOLD)[0]
    prob += pulp.lpSum(x[i] for i in covering_facilities) >= 1

print("Solving ILP (may take a while depending on problem size)...")
solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=SOLVER_TIME_LIMIT)
prob.solve(solver)

ilp_elapsed = time.time() - ilp_start
print(f"ILP solve time: {ilp_elapsed:.2f} s ({ilp_elapsed/60:.2f} min)")

status = pulp.LpStatus[prob.status]
print(f"Solver status: {status}")

chosen_idxs = [i for i in range(N) if x[i].value() == 1]
print(f"\nMinimum K found: {len(chosen_idxs)}")

achieved_radius = D[chosen_idxs, :].min(axis=0).max()
print(f"Achieved radius with this placement: {achieved_radius:.2f} m")

# ---- Export ----
chosen_nodes = [nodes[i] for i in chosen_idxs]
out = gpd.GeoDataFrame(
    {"radius": [achieved_radius]*len(chosen_nodes)},
    geometry=gpd.points_from_xy([c[0] for c in chosen_nodes], [c[1] for c in chosen_nodes]),
    crs=gdf.crs
)
out_path = r"C:\Users\Student\Downloads\optimal_min_k_100m.gpkg"
out.to_file(out_path, driver="GPKG")
print(f"Saved {len(chosen_nodes)} nodes to {out_path}")

total_elapsed = time.time() - total_start
print(f"\nTotal script runtime: {total_elapsed:.2f} s ({total_elapsed/60:.2f} min)")
