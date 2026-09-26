import os
import math
import heapq
from qgis.core import (
    QgsProject, 
    QgsGeometry, 
    QgsPointXY, 
    QgsFeature, 
    QgsVectorLayer, 
    QgsField,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsSpatialIndex
)
from qgis.PyQt.QtCore import QVariant


# ==============================================================================
# 🗺️ 1. CONFIGURATION & LAYER DETECTION
# ==============================================================================
layer = iface.activeLayer()


LENGTH_FIELD      = "seg_length"   
UTCI_FIELD        = "weighted_UTCI"  


# Exact coordinate pins matching your native manual cross-examination tool entries
start_coord       = QgsPointXY(582933.54, 4507092.79)
goal_coord        = QgsPointXY(583459.91, 4507239.99)


if not layer:
    raise ValueError("❌ Error: No active layer selected! Please click on your street network layer in the Layers Panel.")


layer_name = layer.name()
print(f"🚀 INITIALIZING UTCI-MINIMIZING MID-EDGE SPLITTING DIJKSTRA ON: '{layer_name}'...")


# ==============================================================================
# 🏗️ 2. NETWORK INGESTION & DATA STRUCTURE SETUP
# ==============================================================================
spatial_index = QgsSpatialIndex(layer.getFeatures())
features_dict = {f.id(): f for f in layer.getFeatures()}


graph = {}


def add_edge(pt1, pt2, dist, utci, fid, polyline_pts):
    u = (round(pt1.x(), 4), round(pt1.y(), 4))
    v = (round(pt2.x(), 4), round(pt2.y(), 4))
    if u == v: return
    if u not in graph: graph[u] = []
    if v not in graph: graph[v] = []
    graph[u].append((v, dist, utci, fid, polyline_pts))
    graph[v].append((u, dist, utci, fid, polyline_pts))


# Baseline network construction
for f_id, feature in features_dict.items():
    geom = feature.geometry()
    if geom.isNull() or geom.isEmpty(): continue
        
    try:
        length = float(feature[LENGTH_FIELD])
    except (TypeError, ValueError):
        length = geom.length()
        
    utci_mass = 0.0
    try:
        if UTCI_FIELD in [f.name() for f in layer.fields()]:
            val = feature[UTCI_FIELD]
            if val is not None and not isinstance(val, QVariant):
                utci_mass = float(val)
    except (TypeError, ValueError):
        utci_mass = 0.0


    line_points = geom.asGeometryCollection()[0].asPolyline() if geom.isMultipart() else geom.asPolyline()
    if len(line_points) < 2: continue
    
    add_edge(line_points[0], line_points[-1], length, utci_mass, f_id, line_points)


# ==============================================================================
# 🎯 3. DYNAMIC MID-SEGMENT SPLITTING ENGINE
# ==============================================================================
def split_network_at_point(target_pt):
    """Snaps a point to the nearest line segment, splits it, and injects partial segments."""
    nearest_fids = spatial_index.nearestNeighbor(target_pt, 1)
    if not nearest_fids:
        return min(graph.keys(), key=lambda n: math.sqrt((n[0]-target_pt.x())**2 + (n[1]-target_pt.y())**2))
    
    target_fid = nearest_fids[0]
    feat = features_dict[target_fid]
    geom = feat.geometry()
    
    snap_geom = geom.nearestPoint(QgsGeometry.fromPointXY(target_pt))
    snapped_point = snap_geom.asPoint()
    
    line_points = geom.asGeometryCollection()[0].asPolyline() if geom.isMultipart() else geom.asPolyline()
    node_key = (round(snapped_point.x(), 4), round(snapped_point.y(), 4))
    
    try:
        total_len = float(feat[LENGTH_FIELD])
    except (TypeError, ValueError):
        total_len = geom.length()
        
    total_utci = 0.0
    try:
        if UTCI_FIELD in [f.name() for f in layer.fields()]:
            val = feat[UTCI_FIELD]
            if val is not None and not isinstance(val, QVariant):
                total_utci = float(val)
    except (TypeError, ValueError):
        pass


    # Find where the snapped point falls within the vertex list to split it cleanly
    min_dist = float('inf')
    insert_idx = 1
    
    for i in range(len(line_points) - 1):
        seg_geom = QgsGeometry.fromPolylineXY([line_points[i], line_points[i+1]])
        dist = seg_geom.distance(snap_geom)
        if dist < min_dist:
            min_dist = dist
            insert_idx = i + 1


    pts_part1 = line_points[:insert_idx] + [snapped_point]
    pts_part2 = [snapped_point] + line_points[insert_idx:]
    
    geom_len1 = QgsGeometry.fromPolylineXY(pts_part1).length()
    geom_len2 = QgsGeometry.fromPolylineXY(pts_part2).length()
    geom_total = geom_len1 + geom_len2 if (geom_len1 + geom_len2) > 0 else 1.0
    
    len1 = (geom_len1 / geom_total) * total_len
    len2 = (geom_len2 / geom_total) * total_len
    utci1 = (geom_len1 / geom_total) * total_utci
    utci2 = (geom_len2 / geom_total) * total_utci
    
    add_edge(line_points[0], snapped_point, len1, utci1, target_fid, pts_part1)
    add_edge(snapped_point, line_points[-1], len2, utci2, target_fid, pts_part2)
    
    return node_key


start_node = split_network_at_point(start_coord)
end_node = split_network_at_point(goal_coord)


# ==============================================================================
# 🧠 4. DIJKSTRA ENGINE (OPTIMIZED FOR UTCI MINIMIZATION)
# ==============================================================================
# The distances dictionary now maps nodes to their minimum encountered UTCI cost
utci_costs = {node: float('inf') for node in graph}
utci_costs[start_node] = 0.0


# Priority Queue schema: (current_accumulated_utci, current_node, current_accumulated_dist, path_edges)
priority_queue = [(0.0, start_node, 0.0, [])]
best_route = None


while priority_queue:
    pop_item = heapq.heappop(priority_queue)
    curr_utci  = pop_item[0]
    curr_node  = pop_item[1]
    curr_dist  = pop_item[2]
    path_edges = pop_item[3]
    
    if curr_node == end_node:
        best_route = (curr_dist, curr_utci, path_edges)
        break
        
    if curr_utci > utci_costs[curr_node]:
        continue
        
    if curr_node not in graph: continue
    for neighbor, edge_len, edge_utci, f_id, pts in graph[curr_node]:
        next_utci = curr_utci + edge_utci  
        
        if neighbor in utci_costs and next_utci < utci_costs[neighbor]:
            utci_costs[neighbor] = next_utci
            heapq.heappush(priority_queue, (
                next_utci, 
                neighbor, 
                curr_dist + edge_len, 
                path_edges + [(f_id, edge_len, edge_utci, pts)]
            ))


# ==============================================================================
# 🏆 5. GENERATING UTCI OPTIMIZED LAYER OUTPUT
# ==============================================================================
if best_route is not None:
    final_length    = best_route[0]
    final_utci_mass = best_route[1]
    route_segments  = best_route[2]
    
    print("\n" + "="*60)
    print(f"🏁 HIGH-PRECISION THERMAL COMFORT RESULTS FOR LAYER: {layer_name}")
    print("="*60)
    print(f"🌡️ MINIMIZED PATH UTCI MASS: {final_utci_mass:.2f} units")
    print(f"📏 CORRESPONDING PATH DISTANCE: {final_length:.2f} meters")
    print("="*60 + "\n")
    
    clean_name = "".join([c if c.isalnum() or c in ('_', '-') else '' for c in layer_name])
    output_layer_title = f"Coolest_TrueSplit_Path_{clean_name}"
    
    crs_string = layer.crs().authid()
    route_layer = QgsVectorLayer(f"LineString?crs={crs_string}", output_layer_title, "memory")
    provider = route_layer.dataProvider()
    
    provider.addAttributes([
        QgsField("origin_fid", QVariant.Int),
        QgsField(LENGTH_FIELD, QVariant.Double),
        QgsField("route_utci", QVariant.Double)
    ])
    route_layer.updateFields()
    
    new_features = []
    for f_id, seg_len, seg_utci, pts in route_segments:
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
        feat.setAttributes([f_id, seg_len, seg_utci])
        new_features.append(feat)
        
    provider.addFeatures(new_features)
    route_layer.updateExtents()
    
    project_path = QgsProject.instance().homePath() or os.path.expanduser("~")
    full_gpkg_path = os.path.join(project_path, f"{output_layer_title}.gpkg")
    
    save_options = QgsVectorFileWriter.SaveVectorOptions()
    save_options.driverName = "GPKG"
    save_options.layerName = output_layer_title
    
    write_result = QgsVectorFileWriter.writeAsVectorFormatV3(route_layer, full_gpkg_path, QgsCoordinateTransformContext(), save_options)
    
    if write_result[0] == QgsVectorFileWriter.NoError:
        QgsProject.instance().addMapLayer(QgsVectorLayer(f"{full_gpkg_path}|layername={output_layer_title}", output_layer_title, "ogr"))
        print(f"💾 Thermal optimized geometric output loaded from project space: {full_gpkg_path}")
    else:
        QgsProject.instance().addMapLayer(route_layer)
        print("📁 Loaded as virtual temporary tracking scratch layer.")
else:
    print("❌ Critical connection error: No valid route found using split projection metrics.")



