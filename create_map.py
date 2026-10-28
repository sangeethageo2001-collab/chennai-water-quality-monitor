
from pathlib import Path
import geopandas as gpd
import folium
import html
import math

# Project paths
data_dir = Path("Data")
output_dir = Path("outputs")
output_dir.mkdir(exist_ok=True)

boundary_file = data_dir / "Chennai_new.shp"
points_file = data_dir / "Point_Data.shp"

# Choose the heavy metal to display
metal_field = "Pb_mg_L"  # Lead; change to Cd_mg_L, Cr_mg_L, etc.

# Load GIS data
boundary = gpd.read_file(boundary_file).to_crs("EPSG:4326")
points = gpd.read_file(points_file).to_crs("EPSG:4326")

if points.empty:
    raise ValueError("No water-sampling points were found.")

if metal_field not in points.columns:
    raise ValueError(f"Field not found: {metal_field}")

# Find map centre from the sampling points
valid_points = points[
    points.geometry.notna() & ~points.geometry.is_empty
]

if valid_points.empty:
    raise ValueError("No valid point geometries were found.")

center_lat = valid_points.geometry.y.mean()
center_lon = valid_points.geometry.x.mean()

# Create interactive map

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=10,
    tiles=None
)

minx, miny, maxx, maxy = boundary.total_bounds

m.fit_bounds([
    [miny, minx],
    [maxy, maxx]
])

# Add Chennai boundary
folium.GeoJson(
    boundary.to_json(),
    name="Chennai boundary",
    style_function=lambda feature: {
        "color": "#2457A7",
        "weight": 2,
        "fillOpacity": 0.05
    },
    tooltip="Chennai boundary"
).add_to(m)

# Parse concentration values
points[metal_field] = __import__("pandas").to_numeric(
    points[metal_field], errors="coerce"
)

values = points[metal_field].dropna()

if values.empty:
    raise ValueError(f"No numeric values found in {metal_field}.")

# Relative display classes, NOT toxicity thresholds
low_cut = values.quantile(1 / 3)
high_cut = values.quantile(2 / 3)

def marker_color(value):
    if value <= low_cut:
        return "green"
    elif value <= high_cut:
        return "orange"
    return "red"

for _, row in points.iterrows():
    geom = row.geometry

    if geom is None or geom.is_empty:
        continue

    value = row[metal_field]

    if value is None or not math.isfinite(float(value)):
        color = "gray"
        concentration = "No data"
    else:
        value = float(value)
        color = marker_color(value)
        concentration = f"{value:.6g} mg/L"

    site_id = html.escape(str(row.get("Site_ID", "Unknown")))
    site_name = html.escape(str(row.get("Site_Name", "Unknown")))
    metal_name = html.escape(metal_field)

    popup_html = f"""
    <b>Site ID:</b> {site_id}<br>
    <b>Site name:</b> {site_name}<br>
    <b>Parameter:</b> {metal_name}<br>
    <b>Concentration:</b> {concentration}<br>
    <b>Dataset status:</b> Synthetic/not measured
    """

    folium.CircleMarker(
        location=[geom.y, geom.x],
        radius=7,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.8,
        popup=folium.Popup(popup_html, max_width=300),
        tooltip=f"{site_id}: {concentration}"
    ).add_to(m)

# Add map legend
legend = """
<div style="
position: fixed; bottom: 30px; left: 30px; z-index: 9999;
background: white; padding: 12px; border: 1px solid #999;
border-radius: 5px;">
<b>Relative concentration</b><br>
<span style="color:green;">●</span> Lower third<br>
<span style="color:orange;">●</span> Middle third<br>
<span style="color:red;">●</span> Upper third<br>
<span style="color:gray;">●</span> Missing value<br>
<small>Relative classes only; not safety thresholds.</small>
</div>
"""

m.get_root().html.add_child(folium.Element(legend))
folium.LayerControl().add_to(m)

# Export spatial data and interactive map
boundary.to_file(
    output_dir / "chennai_boundary.geojson",
    driver="GeoJSON"
)
points.to_file(
    output_dir / "water_samples.geojson",
    driver="GeoJSON"
)

map_file = output_dir / "chennai_water_quality_map.html"
m.save(str(map_file))

print("Map created successfully!")
print("Sampling points:", len(points))
print("Displayed parameter:", metal_field)
print("Map file:", map_file.resolve())
print("Open the HTML file in your browser.")
