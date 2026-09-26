import os
import glob
import processing

# ==============================================================================
# 🛠️ CONFIGURATION - University Desktop Structure
# ==============================================================================
# Path to your current massive folder with the 2209 files
input_folder = r"C:\Users\Student\Downloads\bigtile5_solweig"

# Where you want the new, clean averaged folders to be created
output_parent_folder = r"C:\Users\Student\Downloads\bigtile5_avg_outputs"

# Change this if you run other tiles later (e.g., "bigtile6")
tile_name = "bigtile5"
# ==============================================================================

# Define the time blocks we care about based on SOLWEIG's naming convention
time_blocks = {
    "morning": ["1000D", "1100D", "1200D"],
    "afternoon": ["1300D", "1400D", "1500D"],
    "evening": ["1600D", "1700D", "1800D"]
}

print(f"🚀 Starting time-block averaging pipeline for {tile_name} via GDAL...")

# Ensure the main output folder exists cleanly
os.makedirs(output_parent_folder, exist_ok=True)

# 1. Figure out all the unique Julian days present in your folder (152 to 243)
all_tifs = glob.glob(os.path.join(input_folder, "Tmrt_*.tif"))
julian_days = set()

for f in all_tifs:
    parts = os.path.basename(f).split('_')
    if len(parts) >= 3:
        julian_days.add(parts[2])

sorted_days = sorted(list(julian_days))
print(f"📅 Found {len(sorted_days)} days to process (Days {sorted_days[0]} to {sorted_days[-1]}).")

# 2. Loop day by day
for day in sorted_days:
    print(f"📦 Processing Day {day}...")
    
    day_output_dir = os.path.join(output_parent_folder, f"Day_{day}")
    os.makedirs(day_output_dir, exist_ok=True)
    
    # 3. Process morning, afternoon, and evening blocks for this day
    for block_name, hours in time_blocks.items():
        files_to_average = []
        
        # Build paths for the 3 hours needed for this block
        for hour in hours:
            expected_file = os.path.join(input_folder, f"Tmrt_2017_{day}_{hour}.tif")
            if os.path.exists(expected_file):
                files_to_average.append(expected_file)
        
        # Only process if we found all 3 hourly files for the block
        if len(files_to_average) == 3:
            # FIXED: Custom naming syntax -> e.g., 152_morning_bigtile5.tif
            custom_filename = f"{day}_{block_name}_{tile_name}.tif"
            output_file_path = os.path.join(day_output_dir, custom_filename)
            
            # Run the GDAL processing algorithm
            processing.run("gdal:rastercalculator", {
                'INPUT_A': files_to_average[0],
                'BAND_A': 1,
                'INPUT_B': files_to_average[1],
                'BAND_B': 1,
                'INPUT_C': files_to_average[2],
                'BAND_C': 1,
                'FORMULA': '(A + B + C) / 3.0',
                'NO_DATA_VALUE': None,
                'RTYPE': 5,  # Float32 type to keep exact temperature decimals
                'OPTIONS': '',
                'EXTRA': '',
                'OUTPUT': output_file_path
            })
        else:
            print(f"⚠️ Missing files for Day {day} {block_name} block. Skipping this block.")

print(f"\n🎉 Complete! Check your customized outputs here: {output_parent_folder}")

