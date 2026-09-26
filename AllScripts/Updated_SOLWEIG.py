import os
import glob
import re
from qgis.core import QgsProject, QgsRasterLayer
import processing

# =======================================================
# DIRECTORY SETUP (Flattened to Downloads)
# =======================================================
USER_PROFILE = os.environ['USERPROFILE'].replace('\\', '/')
DOWNLOADS_DIR = f"{USER_PROFILE}/Downloads"

# Everything now reads from and writes to the Downloads folder directly
JUMBO_FOLDER = DOWNLOADS_DIR
BUFFERED_SVF_FOLDER = DOWNLOADS_DIR

BUFFERED_GRID_NAME = "grid600m-buffer300m"  
GRID_ID_COLUMN = "fid"
# =======================================================

buffered_grid = QgsProject.instance().mapLayersByName(BUFFERED_GRID_NAME)[0]

jumbo_mapping = {
    "zDSMx_meters_2x2.tif":       ("DSMx",       -5,    1500),
    "zDEM_meters_2x2.tif":        ("DEM",        -5,    9000),
    "WholeWallHeight.tif":        ("WallHeight",  0,    1500), 
    "WholeWallAspect.tif":        ("WallAspect",  0,    360), 
    "zCHM_meters_2x2.tif":        ("CHM",        -5,    150),
}

print(" starting grid-matching warp-calc pipeline...")

for zip_path in glob.glob(os.path.join(BUFFERED_SVF_FOLDER, "*.zip")):
    zip_name = os.path.basename(zip_path)
    match = re.search(r'\d+', zip_name)
    if not match:
        continue

    tile_id = match.group()
    print(f"\nprocessing tile id: {tile_id}")

    # Output directly to your Downloads folder using the #_solweig_inputs format
    tile_out_dir = f"{DOWNLOADS_DIR}/{tile_id}_solweig_inputs"
    os.makedirs(tile_out_dir, exist_ok=True)

    svf_files = glob.glob(os.path.join(BUFFERED_SVF_FOLDER, f"{tile_id}svfs*"))
    if not svf_files:
        svf_files = glob.glob(os.path.join(BUFFERED_SVF_FOLDER, f"*{tile_id}*svfs*"))
        
    if not svf_files:
        print(f"error: could not find an svf file named '{tile_id}svfs'. skipping.")
        continue
        
    svf_path = svf_files[0]
    print(f"found svf: {os.path.basename(svf_path)}")

    buffered_grid.setSubsetString(f'"{GRID_ID_COLUMN}" = \'{tile_id}\'')
    if buffered_grid.featureCount() == 0:
        buffered_grid.setSubsetString('')
        continue

    for jumbo_name, (layer_label, min_valid, max_valid) in jumbo_mapping.items():
        jumbo_path = f"{JUMBO_FOLDER}/{jumbo_name}"
        if not os.path.exists(jumbo_path):
            print(f"Skipping missing master file: {jumbo_name}")
            continue

        temp_clip = f"{tile_out_dir}/temp_clip_{layer_label}.tif"
        final_out = f"{tile_out_dir}/{tile_id}{layer_label}.tif"

        print(f"warping/snapping {tile_id}{layer_label} to match svf dimensions...")

        processing.run("gdal:warpreproject", {
            'INPUT': jumbo_path,
            'SOURCE_CRS': None,
            'TARGET_CRS': None,
            'RESAMPLING': 0,     
            'NODATA': None,
            'TARGET_RESOLUTION': None,
            'OPTIONS': '',
            'DATA_TYPE': 0,    
            'TARGET_EXTENT': None,
            'EXTRA': f'-te_srs EPSG:32618 -target_aligned_pixels', # Adjust EPSG if your project isn't UTM 18N
            'OUTPUT': temp_clip
        })
        
        svf_layer = QgsRasterLayer(svf_path, "svf_anchor")
        ext = svf_layer.extent()
        
        processing.run("gdal:cliprasterbymasklayer", {
            'INPUT': jumbo_path,
            'MASK': buffered_grid,
            'CROP_TO_CUTLINE': True,
            'KEEP_RESOLUTION': False, 
            'EXTRA': f'-te {ext.xMinimum()} {ext.yMinimum()} {ext.xMaximum()} {ext.yMaximum()} -ts {svf_layer.width()} {svf_layer.height()}', 
            'OUTPUT': temp_clip
        })

        gdal_expression = f"(A >= {min_valid}) * (A <= {max_valid}) * A"
        
        processing.run("gdal:rastercalculator", {
            'INPUT_A': temp_clip,
            'BAND_A': 1,
            'FORMULA': gdal_expression,
            'NO_DATA': None, 
            'RTYPE': 5,      
            'EXTRA': '--NoDataValue=None', 
            'OUTPUT': final_out
        })

        if os.path.exists(temp_clip):
            try: os.remove(temp_clip)
            except: pass

    buffered_grid.setSubsetString('')

print("\n🎉🎉🎉 done!!!!!!!!!!")

