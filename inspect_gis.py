
from pathlib import Path
import geopandas as gpd

data_folder = Path("Data")

files = {
    "Chennai boundary": data_folder / "Chennai_new.shp",
    "Water sampling points": data_folder / "Point_Data.shp",
}

for label, file_path in files.items():
    print(f"\n--- {label} ---")

    if not file_path.exists():
        print(f"File not found: {file_path}")
        continue

    gdf = gpd.read_file(file_path)

    print("Feature count:", len(gdf))
    print("CRS:", gdf.crs)
    print("Geometry types:",
          gdf.geometry.geom_type.value_counts().to_dict())
    print("Columns:", gdf.columns.tolist())
    print("\nFirst five records:")
    print(gdf.drop(columns="geometry").head().to_string(index=False))
