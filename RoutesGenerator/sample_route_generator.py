from give_routes_discomfort_geopandas import find_alternative_discomfort_routes

routes = find_alternative_discomfort_routes(
    input_gpkg="route_08_12.gpkg",
    output_dir="./all_routes",
    input_layer="route_08_12",
    start_coord=(582933.54, 4507092.79),
    end_coord=(583459.91, 4507239.99),
    length_field="Shape_Leng",
    discomfort_field="cd",
    stretch_factor=1.00,
    time_stamp="08_12"
)

print(f"Generated {len(routes)} route(s).")
