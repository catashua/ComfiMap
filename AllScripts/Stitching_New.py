import os
import zipfile
import glob
import time
from qgis.core import *
import processing

# --- USER CONFIGURATION ---
DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
SOLWEIG_DIR = os.path.join(DOWNLOADS_DIR, "SOLWEIG_Project")
ZIPS_DIR = os.path.join(SOLWEIG_DIR, "zips")
TEMP_DIR = os.path.join(SOLWEIG_DIR, "temp_processing")

UNBUFFERED_LAYER_NAME = "updated-grid600m — grid600m" 
ID_COLUMN = "testing"   
IMAGE_EXTENSION = ".tif"
FOLDER_SUFFIX = "epw_solweig"  # Appended after tile_id (e.g. <tile_id>_epw_solweig)
# --------------------------

start_all = time.time()

os.makedirs(TEMP_DIR, exist_ok=True)

print(">> Step 1: Scanning zip archives...")
zip_files = glob.glob(os.path.join(ZIPS_DIR, "*.zip"))
if not zip_files:
    raise Exception(f"No zip files found in {ZIPS_DIR}!")

tile_ids = []
for zip_path in zip_files:
    tile_id = os.path.basename(zip_path).split('_')[0]
    tile_ids.append(tile_id)

tile_ids.sort(key=lambda x: int(x) if x.isdigit() else x)
folder_name = f"{'_'.join(tile_ids)}_{FOLDER_SUFFIX}"
OUTPUT_DIR = os.path.join(DOWNLOADS_DIR, folder_name)
os.makedirs(OUTPUT_DIR, exist_ok=True)

print("\n>> Step 2: Indexing vector layer and setting target CRS alignment...")
layers = QgsProject.instance().mapLayersByName(UNBUFFERED_LAYER_NAME)
if not layers:
    raise Exception(f"Layer '{UNBUFFERED_LAYER_NAME}' not found.")
grid_layer = layers[0]
CRS_TARGET = grid_layer.crs().authid()

print("\n>> Step 3: Mapping timeline...")
sample_zip_path = zip_files[0]
timestep_filenames = []
with zipfile.ZipFile(sample_zip_path, 'r') as z:
    for name in z.namelist():
        if name.endswith(IMAGE_EXTENSION):
            timestep_filenames.append(os.path.basename(name))

timestep_filenames.sort()

print("\n>> Step 4: Running Mask-Based Clip & Stitch Process...")
for idx, timestep in enumerate(timestep_filenames, 1):
    clipped_rasters_this_step = []
    
    for zip_path in zip_files:
        tile_id = os.path.basename(zip_path).split('_')[0]
        
        # Dynamic internal zip path: <tile_id>_epw_solweig/<timestep>
        internal_zip_path = f"{tile_id}_{FOLDER_SUFFIX}/{timestep}"
        temp_extract_path = os.path.join(TEMP_DIR, f"raw_{tile_id}_{timestep}.tif")
        temp_clipped_path = os.path.join(TEMP_DIR, f"clip_{tile_id}_{timestep}.tif")
        
        try:
            # 1. Extract raw individual file
            with zipfile.ZipFile(zip_path, 'r') as z:
                with open(temp_extract_path, "wb") as f:
                    f.write(z.read(internal_zip_path))
            
            # 2. Extract ONLY the single matching grid square vector feature to use as a mask
            expr = f'"{ID_COLUMN}" = \'{tile_id}\''
            selection_layer = grid_layer.materialize(QgsFeatureRequest().setFilterExpression(expr))
            
            if selection_layer.featureCount() == 0:
                if os.path.exists(temp_extract_path): 
                    os.remove(temp_extract_path)
                continue
                
            # 3. Mask clip using vector geometry
            processing.run("gdal:cliprasterbymasklayer", {
                'INPUT': temp_extract_path,
                'MASK': selection_layer,
                'SOURCE_CRS': CRS_TARGET,
                'TARGET_CRS': CRS_TARGET,
                'NODATA': 0,
                'ALPHA_BAND': False,
                'CROP_TO_CUTLINE': True,
                'KEEP_RESOLUTION': True,
                'OPTIONS': '',
                'DATA_TYPE': 5,
                'OUTPUT': temp_clipped_path
            })
            
            clipped_rasters_this_step.append(temp_clipped_path)
            
            if os.path.exists(temp_extract_path):
                os.remove(temp_extract_path)
                
        except KeyError:
            continue
        except Exception as e:
            print(f"    Warning: Error processing Tile {tile_id} at {timestep}: {e}")

    # 4. Mosaic clipped chunks together
    if clipped_rasters_this_step:
        final_output_path = os.path.join(OUTPUT_DIR, timestep)
        
        processing.run("gdal:merge", {
            'INPUT': clipped_rasters_this_step,
            'PCT': False,
            'SEPARATE': False,
            'NODATA_INPUT': 0,
            'NODATA_OUTPUT': 0,
            'OPTIONS': '',
            'DATA_TYPE': 5,
            'OUTPUT': final_output_path
        })
        
        # Clear temporary clipped files
        for temp_clip in clipped_rasters_this_step:
            if os.path.exists(temp_clip):
                os.remove(temp_clip)

end_all = time.time()
total_duration = end_all - start_all

mins, secs = divmod(total_duration, 60)
hours, mins = divmod(mins, 60)

print("\n" + "="*50)
print(f">> Pipeline Complete! Files saved to: {OUTPUT_DIR}")
print(f">> Total Execution Time: {int(hours)}h {int(mins)}m {secs:.2f}s")
print("="*50)


