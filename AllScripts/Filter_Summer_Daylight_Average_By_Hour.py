import os
import glob
import time
from qgis.core import *
import processing

# --- USER CONFIGURATION ---
DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")

# Folder name containing your combined SOLWEIG tifs
INPUT_FOLDER_NAME = "100_126_127_128_151_152_153_176_177_178_202_epw_solweig"
INPUT_DIR = os.path.join(DOWNLOADS_DIR, INPUT_FOLDER_NAME)

# Output directory for hourly averages per month
OUTPUT_DIR = os.path.join(INPUT_DIR, "averages")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Define Day-of-Year (DOY) ranges for the summer months
MONTH_RANGES = {
    "june": (152, 181),
    "july": (182, 212),
    "august": (213, 243)
}

# --------------------------

start_time = time.time()
print(f">> Starting Hourly Diurnal Averaging for: {INPUT_FOLDER_NAME}")

if not os.path.exists(INPUT_DIR):
    raise Exception(f"Directory not found: {INPUT_DIR}")

# Step 1: Scan all .tif files
all_tif_paths = glob.glob(os.path.join(INPUT_DIR, "*.tif"))
if not all_tif_paths:
    raise Exception(f"No .tif files found in {INPUT_DIR}")

print(f">> Found {len(all_tif_paths)} total raster files.")

# Step 2: Group files by (Month, Hourly Timestamp)
# Filename structure: Tmrt_1985_161_1200D.tif
# Grouping Key: (month_name, "1200D")
hourly_groups = {}

for file_path in all_tif_paths:
    filename = os.path.basename(file_path)
    filename_no_ext = os.path.splitext(filename)[0]
    
    parts = filename_no_ext.split('_')
    if len(parts) < 4:
        continue
        
    try:
        doy = int(parts[2])
    except ValueError:
        continue

    hour_str = parts[3]  # Extracts "1200D", "0100N", etc.

    # Identify month based on DOY
    target_month = None
    for month_name, (start_doy, end_doy) in MONTH_RANGES.items():
        if start_doy <= doy <= end_doy:
            target_month = month_name
            break
            
    if not target_month:
        continue  # File is outside June, July, August

    # Add to dictionary using (month, hour) as key
    key = (target_month, hour_str)
    if key not in hourly_groups:
        hourly_groups[key] = []
    hourly_groups[key].append(file_path)

print(f">> Grouped into {len(hourly_groups)} distinct hourly buckets across the 3 months.")

# Step 3: Calculate pixel-wise average for each (Month, Hour) combination
total_runs = len(hourly_groups)
completed = 0

for (month_name, hour_str), files in sorted(hourly_groups.items()):
    completed += 1
    
    # Example output: june_avg_1200D.tif
    output_filename = f"{month_name}_avg_{hour_str}.tif"
    output_file = os.path.join(OUTPUT_DIR, output_filename)
    
    # Build QGIS Raster Calculator expression
    sum_terms = []
    input_layers = {}
    
    for idx, path in enumerate(files, 1):
        layer_alias = f"r{idx}"
        sum_terms.append(f'"{layer_alias}@1"')
        input_layers[layer_alias] = path

    expression = f"({' + '.join(sum_terms)}) / {len(files)}"

    sample_raster = QgsRasterLayer(files[0], "sample")

    # Run QGIS Raster Calculator
    processing.run("qgis:rastercalculator", {
        'EXPRESSION': expression,
        'LAYERS': list(input_layers.values()),
        'CELLSIZE': sample_raster.rasterUnitsPerPixelX(),
        'EXTENT': sample_raster.extent(),
        'CRS': sample_raster.crs().authid(),
        'OUTPUT': output_file
    })

    if completed % 12 == 0 or completed == total_runs:
        print(f"   Progress: Saved {completed}/{total_runs} rasters -> {output_filename}")

elapsed = time.time() - start_time
print("\n" + "="*50)
print(f">> Diurnal Hourly Averaging Complete!")
print(f">> Output directory: {OUTPUT_DIR}")
print(f">> Total Rasters Created: {total_runs} (Expected ~72)")
print(f">> Execution Time: {elapsed:.2f} seconds")
print("="*50)


