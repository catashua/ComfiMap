import osmnx as ox

ox.settings.cache_folder = r"C:\Users\Student\Documents\osmnx_cache"

cf = (
    '["highway"~"footway|path|pedestrian|steps|living_street|track|corridor|unclassified|cycleway|bridleway"]'
    '["access"!~"no|private"]'
    '["foot"!~"no|private"]'
)
# By place name
G = ox.graph_from_place("Manhattan, New York, USA", custom_filter=cf)

# By point + distance (meters)
#G = ox.graph_from_point((40.758, -73.9855), dist=1000, network_type="walk")

# By polygon (e.g. a GeoDataFrame boundary)
#G = ox.graph_from_polygon(my_polygon, network_type="walk")

# Save / convert
ox.save_graph_geopackage(G, filepath=r"C:\Users\Student\Downloads\osm_manhattan_pedestrian_network.gpkg")
gdf_nodes, gdf_edges = ox.graph_to_gdfs(G)



