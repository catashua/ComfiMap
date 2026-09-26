import os
import csv
from qgis.core import (
    QgsVectorLayer,
    QgsPointXY,
    QgsFeature,
    QgsCoordinateReferenceSystem,
    QgsVectorFileWriter,
    QgsFields,
    QgsField,
    Qgis
)
from qgis.analysis import (
    QgsVectorLayerDirector,
    QgsGraphBuilder,
    QgsGraphAnalyzer
)
from PyQt5.QtCore import QVariant

# ==============================================================================
# PATH CONFIGURATION FOR USER 'student'
# ==============================================================================
DOWNLOADS_DIR = "C:/Users/student/Downloads"  # Change to "/Users/student/Downloads" if on Mac

# Updated file name matching your download
CSV_PATH = os.path.join(DOWNLOADS_DIR, "20 point in fidi.csv")
GPKG_PATH = os.path.join(DOWNLOADS_DIR, "edge.gpkg")  # Your network file
OUTPUT_XLSX = os.path.join(DOWNLOADS_DIR, "od_pairs.xlsx")     # Final Excel output

DISTANCE_LIMIT_MILES = .39
DISTANCE_LIMIT_METERS = DISTANCE_LIMIT_MILES * 1609.344         # ~627.8 meters

TARGET_CRS = QgsCoordinateReferenceSystem("EPSG:32618")

# ==============================================================================
# STEP 1: LOAD CSV POINTS
# ==============================================================================
print(f"Loading points from CSV: {CSV_PATH}...")
points_dict = {}

if not os.path.exists(CSV_PATH):
    raise FileNotFoundError(f"Could not find CSV file at {CSV_PATH}. Please verify the file name in Downloads.")

with open(CSV_PATH, mode='r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        # Handles column headers regardless of casing or extra spaces
        row_lower = {k.strip().lower(): v.strip() for k, v in row.items()}
        
        point_id = row_lower['point #'] if 'point #' in row_lower else row_lower['point']
        x = float(row_lower['long'])
        y = float(row_lower['lat'])
        
        points_dict[point_id] = QgsPointXY(x, y)

print(f"Successfully loaded {len(points_dict)} points.")

# ==============================================================================
# STEP 2: BUILD PEDESTRIAN NETWORK GRAPH
# ==============================================================================
print("Building network graph from GPKG...")
network_layer = QgsVectorLayer(GPKG_PATH, "pedestrian_network", "ogr")

if not network_layer.isValid():
    raise RuntimeError(f"Could not load network file at: {GPKG_PATH}")

# Set up director for bidirectional pedestrian movement
director = QgsVectorLayerDirector(
    network_layer,
    -1, "", "", "", 
    QgsVectorLayerDirector.DirectionBoth
)

builder = QgsGraphBuilder(TARGET_CRS)
director.makeGraph(builder, [])
graph = builder.graph()

print("Graph successfully constructed.")

# ==============================================================================
# STEP 3: CALCULATE SHORT PATHS & FIND QUALIFYING PAIRS
# ==============================================================================
print("Finding OD pairs within 1.12 miles...")

# Find nearest graph node for each point
point_vertices = {p_id: graph.findVertex(pt) for p_id, pt in points_dict.items()}
point_ids = list(points_dict.keys())
valid_pairs = set()

# Directed routing calculation (Point 1 -> Point 2)
for orig_id in point_ids:
    orig_v = point_vertices[orig_id]
    
    # Calculate shortest paths from origin node to all other network nodes
    dijkstra_results = QgsGraphAnalyzer.dijkstra(graph, orig_v, 0)
    costs = dijkstra_results[0]
    
    for dest_id in point_ids:
        if orig_id == dest_id:
            continue
            
        dest_v = point_vertices[dest_id]
        dist_meters = costs[dest_v]
        
        # Check if destination node is reachable and within 1.12 miles
        if dist_meters <= DISTANCE_LIMIT_METERS:
            pair_str = f"({orig_id}, {dest_id})"
            valid_pairs.add(pair_str)

# ==============================================================================
# STEP 4: EXPORT SINGLE-COLUMN RESULT TO EXCEL (.XLSX)
# ==============================================================================
print(f"Found {len(valid_pairs)} directed OD pairs within distance threshold.")

fields = QgsFields()
fields.append(QgsField("OD_Pairs", QVariant.String))

writer = QgsVectorFileWriter(
    OUTPUT_XLSX,
    "UTF-8",
    fields,
    Qgis.WkbType.NoGeometry,
    TARGET_CRS,
    "XLSX"
)

# Sorting helper function to sort numerical string values nicely (e.g., 1, 2, ..., 10 instead of 1, 10, 2)
def natural_sort_key(s):
    import re
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

if writer.hasError() != QgsVectorFileWriter.NoError:
    # Fallback to CSV if local GDAL build does not support direct XLSX writing
    fallback_csv = os.path.join(DOWNLOADS_DIR, "od_pairs.csv")
    with open(fallback_csv, 'w', newline='', encoding='utf-8') as f:
        f.write("OD_Pairs\n")
        for pair in sorted(valid_pairs, key=natural_sort_key):
            f.write(f'"{pair}"\n')
    print(f"XLSX driver unavailable. Exported as CSV instead to: {fallback_csv}")
else:
    sorted_pairs = sorted(valid_pairs, key=natural_sort_key)
    
    for pair in sorted_pairs:
        feat = QgsFeature(fields)
        feat.setAttribute("OD_Pairs", pair)
        writer.addFeature(feat)
        
    del writer  # Write output to disk
    print(f"Done! Excel file saved to: {OUTPUT_XLSX}")


