import os
import glob
import pandas as pd
import numpy as np

DATA_DIR = r"C:\Users\sister\Downloads\Trickee\battery_data\Battery_data"
EXPORT_DIR = r"C:\Users\sister\Downloads\Trickee\battery_data\hf_export"

os.makedirs(EXPORT_DIR, exist_ok=True)

VEHICLES = sorted([
    d.replace("CU4Gflash_can_", "")
    for d in os.listdir(DATA_DIR)
    if d.startswith("CU4Gflash_can_CGF") and os.path.isdir(os.path.join(DATA_DIR, d))
])

CELL_COLS = [f"cell_voltage_{i:02d}" for i in range(1, 17)]
TEMP_COLS = ["cell_temperature_01", "cell_temperature_02", "cell_temperature_03"]

print(f"Found {len(VEHICLES)} vehicles. Compressing and exporting to Parquet...")

for v in VEHICLES:
    print(f"Processing CAN {v}...")
    folder = os.path.join(DATA_DIR, f"CU4Gflash_can_{v}")
    csv_path = glob.glob(os.path.join(folder, "*.csv"))
    
    if csv_path:
        # Load and downsample to every 10th row (5 mins if original is 30s)
        # Using 10x downsample makes the data highly performant for UI
        df = pd.read_csv(csv_path[0], parse_dates=["time"])
        df = df.iloc[::10].reset_index(drop=True)
        
        # Clean temp sensors
        for c in TEMP_COLS + ["cell_temperature_04", "cell_temperature_05"]:
            if c in df.columns:
                df[c] = df[c].apply(lambda x: np.nan if x < -10 else x)
                
        # Pre-calculate imbalance
        valid = df[CELL_COLS].replace(0, np.nan)
        df["cell_imbalance_mv"] = (valid.max(axis=1) - valid.min(axis=1)) * 1000
        df["vehicle_id"] = v
        
        # Pre-calculate charge label
        df["charge_label"] = "Idle"
        df.loc[df["current"] > 1, "charge_label"] = "Discharging"
        df.loc[df["current"] < -1, "charge_label"] = "Charging"
        
        # Save as fast parquet
        df.to_parquet(os.path.join(EXPORT_DIR, f"{v}_can.parquet"), index=False)

    print(f"Processing GPS {v}...")
    gps_folder = os.path.join(DATA_DIR, f"CU4Gflash_gps_{v}")
    gps_path = glob.glob(os.path.join(gps_folder, "*.csv"))
    
    if gps_path:
        # GPS dense sampling
        gdf = pd.read_csv(gps_path[0], parse_dates=["time"])
        gdf = gdf.iloc[::20].reset_index(drop=True)
        gdf["vehicle_id"] = v
        
        # Filter invalid GPS upfront
        gdf = gdf[(gdf["latitude"].abs() > 0.1) & (gdf["longitude"].abs() > 0.1)]
        gdf.to_parquet(os.path.join(EXPORT_DIR, f"{v}_gps.parquet"), index=False)

print("\n✅ Done! Data compressed and ready for Hugging Face.")
