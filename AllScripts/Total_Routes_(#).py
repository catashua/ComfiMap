import os
import math
import heapq
from qgis.core import (
    QgsProject, 
    QgsGeometry, 
    QgsPointXY, 
    QgsSpatialIndex,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext
)
from qgis.PyQt.QtCore import QVariant

# ==============================================================================
# 🗺️ 1. CONFIGURATION & LAYER DETECTION
# ==============================================================================
layer = iface.activeLayer()

LENGTH_FIELD      = "seg_length"   
UTCI_FIELD        = "weighted_UTCI"  

START_COORD       = QgsPointXY(582933.54, 4507092.79)
GOAL_COORD        = QgsPointXY(583459.91, 4507239.99)
STRETCH_FACTOR    = 1.03  

if not layer:
    raise ValueError("❌ Error: No active layer selected! Please click on your street network layer in the Layers Panel.")

layer_name = layer.name()
print(f"🚀 INITIALIZING FIXED ISOLATED LAYER GEOPACKAGE GENERATOR ON: '{layer_name}'...")

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

def remove_edge(pt1, pt2, fid):
    u = (round(pt1.x(), 4), round(pt1.y(), 4))
    v = (round(pt2.x(), 4), round(pt2.y(), 4))
    if u in graph:
        graph[u] = [edge for edge in graph[u] if not (edge[0] == v and edge[3] == fid)]
    if v in graph:
        graph[v] = [edge for edge in graph[v] if not (edge[0] == u and edge[3] == fid)]

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
# 🎯 3. DYNAMIC MID-SEGMENT SPLITTING ENGINE (WITH EDGE CLEANUP)
# ==============================================================================
def split_network_at_point(target_pt):
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
    
    # If the point snaps perfectly onto an existing endpoint node, do not split
    if node_key == (round(line_points[0].x(), 4), round(line_points[0].y(), 4)):
        return (round(line_points[0].x(), 4), round(line_points[0].y(), 4))
    if node_key == (round(line_points[-1].x(), 4), round(line_points[-1].y(), 4)):
        return (round(line_points[-1].x(), 4), round(line_points[-1].y(), 4))
    
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
    
    # 🔥 CRITICAL FIX: Erase the parent edge before mapping children sub-segments
    remove_edge(line_points[0], line_points[-1], target_fid)
    
    add_edge(line_points[0], snapped_point, len1, utci1, target_fid, pts_part1)
    add_edge(snapped_point, line_points[-1], len2, utci2, target_fid, pts_part2)
    
    return node_key

start_node = split_network_at_point(START_COORD)
end_node = split_network_at_point(GOAL_COORD)

# ==============================================================================
# 📏 4. TRUE DIJKSTRA ENGINE (FIND BASELINE MINIMUM)
# ==============================================================================
distances = {node: float('inf') for node in graph}
distances[start_node] = 0.0
priority_queue = [(0.0, start_node)]

while priority_queue:
    curr_dist, curr_node = heapq.heappop(priority_queue)
    if curr_node == end_node:
        break
    if curr_dist > distances.get(curr_node, float('inf')):
        continue
    if curr_node not in graph: 
        continue
    for neighbor, edge_len, _, _, _ in graph[curr_node]:
        next_dist = curr_dist + edge_len
        if next_dist < distances.get(neighbor, float('inf')):
            distances[neighbor] = next_dist
            heapq.heappush(priority_queue, (next_dist, neighbor))

shortest_possible_length = distances.get(end_node, float('inf'))
if shortest_possible_length == float('inf'):
    raise ValueError("❌ No physical path connection found between start and end nodes.")

max_allowed_length = shortest_possible_length * STRETCH_FACTOR

print("\n" + "="*60)
print(f"📐 Baseline Shortest Route: {shortest_possible_length:.2f} meters")
print(f"🛑 Maximum Route Distance Threshold ({STRETCH_FACTOR}x): {max_allowed_length:.2f} meters")
print("="*60)

# ==============================================================================
# 🧮 5. EXHAUSTIVE DEPTH-FIRST SEARCH WITH PATH SEPARATION
# ==============================================================================
all_paths_data = []
execution_stack = [(start_node, 0.0, 0.0, [], {start_node})]

while execution_stack:
    curr_node, curr_dist, curr_utci, path_history, visited = execution_stack.pop()
    
    if curr_node == end_node:
        all_paths_data.append((curr_dist, curr_utci, path_history))
        continue
        
    neighbors = graph.get(curr_node, [])
    for neighbor, edge_len, edge_utci, fid, pts in neighbors:
        if neighbor in visited:
            continue
            
        next_dist = curr_dist + edge_len
        if next_dist > max_allowed_length:
            continue
            
        next_utci = curr_utci + edge_utci
        next_history = path_history + [(fid, edge_len, edge_utci, pts)]
        
        execution_stack.append((neighbor, next_dist, next_utci, next_history, visited | {neighbor}))

# ==============================================================================
# 🎨 6. LAYER ISOLATION AND MULTI-LAYER GEOPACKAGE EXPORT
# ==============================================================================
total_paths = len(all_paths_data)

if total_paths > 0:
    print(f"Found {total_paths} valid paths. Writing separate layers to GeoPackage...")
    
    crs_string = layer.crs().authid()
    project_path = QgsProject.instance().homePath() or os.path.expanduser("~")
    
    existing_run_count = 1
    for lyr in QgsProject.instance().mapLayers().values():
        if "Alternative Path" in lyr.name():
            existing_run_count += 1
            
    gpkg_filename = f"Path_Analysis_Run_{existing_run_count}.gpkg"
    full_gpkg_path = os.path.join(project_path, gpkg_filename)
    
    for idx, (total_dist, total_utci, history) in enumerate(all_paths_data, start=1):
        layer_title = f"Alternative Path {idx}"
        
        mem_layer = QgsVectorLayer(f"LineString?crs={crs_string}", layer_title, "memory")
        provider = mem_layer.dataProvider()
        provider.addAttributes([
            QgsField("segment_id", QVariant.Int),
            QgsField(LENGTH_FIELD, QVariant.Double),
            QgsField(UTCI_FIELD, QVariant.Double),
            QgsField("total_dist", QVariant.Double),
            QgsField("total_utci", QVariant.Double)
        ])
        mem_layer.updateFields()
        
        compiled_features = []
        for fid, seg_len, seg_utci, pts in history:
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolylineXY(pts))
            feat.setAttributes([int(fid), float(seg_len), float(seg_utci), float(total_dist), float(total_utci)])
            compiled_features.append(feat)
            
        provider.addFeatures(compiled_features)
        mem_layer.updateExtents()
        
        save_options = QgsVectorFileWriter.SaveVectorOptions()
        save_options.driverName = "GPKG"
        save_options.layerName = f"Path_{idx}"
        
        if idx > 1:
            save_options.actionOnExistingFile = QgsVectorFileWriter.AppendToLayerNoNewFields
            
        write_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            mem_layer, 
            full_gpkg_path, 
            QgsCoordinateTransformContext(), 
            save_options
        )
        
        if write_result[0] == QgsVectorFileWriter.NoError:
            qgis_layer = QgsVectorLayer(f"{full_gpkg_path}|layername=Path_{idx}", layer_title, "ogr")
            QgsProject.instance().addMapLayer(qgis_layer)
        else:
            QgsProject.instance().addMapLayer(mem_layer)
            
    print(f"\n🏆 SUCCESS: Generated {total_paths} layers inside GeoPackage container:\n📄 {full_gpkg_path}")
else:
    print("❌ No alternative paths met your criteria within the threshold boundary.")


