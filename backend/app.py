from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import geopandas as gpd
import json
import os

import find_routes2 as pp
import filter_pareto_routes as fpr

app = Flask(__name__)
# Enable CORS for local testing with your frontend layout
#CORS(app, origins=["http://127.0.0.1", "http://127.0.0.1:8080", "https://comifmap.tech"])
CORS(app, origins="*")

DB_URI = "postgres://tsdbadmin:vvyc0niyiwklnc3l@af1b6u1hca.nj296w7mpf.tsdb.cloud.timescale.com:36845/tsdb?sslmode=require"

def init_db():
    conn = psycopg2.connect(DB_URI)
    cursor = conn.cursor()
    # Log the search queries, timestamp, and metrics directly into Tiger Data
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS route_analytics (
            id SERIAL PRIMARY KEY,
            search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            month INT,
            hour INT,
            start_lat FLOAT,
            start_lon FLOAT,
            end_lat FLOAT,
            end_lon FLOAT
        );
    """)
    conn.commit()
    cursor.close()
    conn.close()

@app.route('/api/navigate', methods=['POST'])
def navigate():
    data = request.json
    s_lat = data.get('start_lat')
    s_lon = data.get('start_lon')
    e_lat = data.get('end_lat')
    e_lon = data.get('end_lon')
    month = data.get('month')
    hour = data.get('hour')
    
    # Connect and save event details instantly to Tiger Data analytics engine
    conn = psycopg2.connect(DB_URI)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO route_analytics (month, hour, start_lat, start_lon, end_lat, end_lon) 
            VALUES (%s, %s, %s, %s, %s, %s);
        """, (month, hour, s_lat, s_lon, e_lat, e_lon))
        conn.commit()

        # -------------------------------------------------------------
        # CORE STEP: Read your processed GeoPackage layers 
        # Using the folder matching your structure: "data/FiDi/clipped/"
        # -------------------------------------------------------------
        
        # NOTE: Substitute this mock response array with your structural algorithm 
        # that loops through your GeoPackages to parse spatial paths.
        # Format the arrays exactly as Leaflet expects: [latitude, longitude]

        # 1. Run the search in memory
        input_gpkg_dataset = f"../data/FiDi/final routes/route_{month:02d}_{hour:02d}.gpkg"


        paths_generated = pp.run(
            input_gpkg=input_gpkg_dataset,
            start_x=s_lon, start_y=s_lat, # Pass as lon/lat format for snapping
            end_x=e_lon, end_y=e_lat,
            output_dir=None,
            percent=15.0,
            max_paths=25,
            coords_crs="EPSG:4326"
        )

        # 2. Map directly to memory coordinate lists cleanly using Shapely head-to-tail line merging
        from shapely.ops import linemerge, unary_union

        '''response_routes = []
        for p in paths_generated:
            gdf = p["gdf"]
            
            # Join the segment lines and sew them continuously in order
            unified_multiline = unary_union(gdf.geometry.values)
            continuous_line = linemerge(unified_multiline)
            
            route_coordinates = []
            
            # Extract points sequentially from the unified track
            if continuous_line.geom_type == 'LineString':
                for x, y in continuous_line.coords:
                    route_coordinates.append([y, x]) # Flip to [Latitude, Longitude] for Leaflet
            else:
                # Fallback handler for true network gaps
                for segment in continuous_line.geoms:
                    for x, y in segment.coords:
                        route_coordinates.append([y, x])

            response_routes.append({
                "name": f"Route Option {p['rank'] + 1}",
                "coordinates": route_coordinates,
                "duration": round(p["total_length"] / 1.4),
                "mean_tmrt": round(p["total_cd"], 2),
                "distance": p["total_length"]
            })'''

        
        # 2. Extract the Pareto paths as standard coordinate sets
        response_routes = fpr.get_pareto_routes_coordinates(paths_generated)
        print("HI")
        if False: # COMMENTCOMMENTCOMMENTCOMMENTCOMMENTCOMMENTCOMMENTCOMMENTCOMMENTCOMMENTCOMMENT
            response_routes = [
                {
                    "name": "Fastest Route",
                    "coordinates": [[s_lat, s_lon], [(s_lat+e_lat)/2, (s_lon+e_lon)/2], [e_lat, e_lon]],
                    "duration": 540,
                    "mean_tmrt": 54.2
                },
                {
                    "name": "Coolest Route",
                    "coordinates": [[s_lat, s_lon], [(s_lat+e_lat)/2 + 0.001, (s_lon+e_lon)/2 + 0.001], [e_lat, e_lon]],
                    "duration": 720,
                    "mean_tmrt": 32.5
                }
            ]
            

        return jsonify({"status": "success", "routes": response_routes})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    init_db()
    port_assignment = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=8080, debug=True)
