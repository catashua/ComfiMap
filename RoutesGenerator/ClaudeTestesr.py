#!/usr/bin/env python3
"""
run_test.py

Test runner script that imports and executes attempt2Claude.py
using specific coordinates and threshold parameters.
"""

from find_routes2 import run
import filter_pareto_routes
import time

def main():
    # Test configuration parameters matching your CLI inputs
    config = {
        "input_gpkg": "route_08_12.gpkg",
        "start_x": 583459.91,
        "start_y": 4507239.99,
        "end_x": 583309.0,
        "end_y": 4506685.6,
        "output_dir": "./all_routes",
        "percent": 10.0,
        "max_paths": 100,
        "coords_crs": "EPSG:32618",  # WGS 84 / UTM zone 18N (matches graph coordinates)
        "clear_output": True         # Clean output directory before saving new paths
    }

    print("=== Running Path Finder Test ===")
    print(f"Network:      {config['input_gpkg']}")
    print(f"Start (X, Y): ({config['start_x']}, {config['start_y']})")
    print(f"End (X, Y):   ({config['end_x']}, {config['end_y']})")
    print(f"Tolerance:    {config['percent']}%")
    print(f"Max Paths:    {config['max_paths']}")
    print(f"Output:       {config['output_dir']}\n")
    start_time = time.time()
    
    # Call the run() function defined in attempt2Claude.py
    results, summary_path = run(
        input_gpkg=config["input_gpkg"],
        start_x=config["start_x"],
        start_y=config["start_y"],
        end_x=config["end_x"],
        end_y=config["end_y"],
        output_dir=config["output_dir"],
        percent=config["percent"],
        max_paths=config["max_paths"],
        coords_crs=config["coords_crs"],
        clear_output=config["clear_output"]
    )
    end_time = time.time()
    timeElapsed = end_time - start_time

    print("\n=== Test Completed Successfully ===")
    print(f"Total paths generated: {len(results)}")
    print(f"Summary file saved at: {summary_path}")
    print(f"Time elapsed: {timeElapsed}")


if __name__ == "__main__":
    main()
    filter_pareto_routes.filter_routes_to_pareto_frontier("./all_routes", "./optimal_routes")
