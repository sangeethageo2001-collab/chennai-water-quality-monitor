"""MapLibre GL JS bridge for Streamlit + GeoPandas.
Uses OpenFreeMap public vector tile styles. Data remains locally in the Streamlit process;
map overlays are embedded as GeoJSON in an HTML iframe.
"""
import json
import math
from pathlib import Path

import pandas as pd
import geopandas as gpd
import streamlit.components.v1 as components

SATELLITE_STYLE = {
    "version": 8,
    "sources": {
        "esri-satellite": {
            "type": "raster",
            "tiles": ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
            "tileSize": 256,
            "maxzoom": 19,
            "attribution": "Imagery © Esri and contributors"
        }
    },
    "layers": [{"id": "esri-world-imagery", "type": "raster", "source": "esri-satellite"}]
}

STYLE_URLS = {
    "Light (Positron)": "https://tiles.openfreemap.org/styles/positron",
    "Streets (Liberty)": "https://tiles.openfreemap.org/styles/liberty",
    "Bright": "https://tiles.openfreemap.org/styles/bright",
    "Dark": "https://tiles.openfreemap.org/styles/dark",
    "Satellite (Esri World Imagery)": SATELLITE_STYLE,
    "No basemap (offline overlays)": {"version": 8, "sources": {}, "layers": [{"id": "background", "type": "background", "paint": {"background-color": "#f2f5f6"}}]},
}


def show_maplibre(boundary: gpd.GeoDataFrame,
                  samples: gpd.GeoDataFrame,
                  metal_column: str,
                  site_column: str | None = None,
                  height: int = 650):
    """Draw boundary + sample points. Inputs should have a defined CRS."""
    if boundary.crs is None or samples.crs is None:
        raise ValueError("Both GeoDataFrames need a CRS. Assign the correct source CRS before calling this function.")
    if metal_column not in samples.columns:
        raise ValueError(f"Metal column {metal_column!r} not found. Columns: {list(samples.columns)}")
    if site_column is None:
        site_column = next((c for c in ["site_name", "Site_Name", "site", "Site", "location", "Location", "name", "Name"] if c in samples.columns), None)

    polygon = boundary.to_crs("EPSG:4326")
    points = samples.to_crs("EPSG:4326")
    x0, y0, x1, y1 = (float(v) for v in polygon.total_bounds)
    if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
        raise ValueError("Boundary has no valid geographic extent")

    boundary_json = json.loads(polygon[["geometry"]].to_json())
    features = []
    valid_values = pd.to_numeric(points[metal_column], errors="coerce").dropna()
    if valid_values.empty:
        raise ValueError(f"No numeric concentrations in {metal_column}")
    q1 = float(valid_values.quantile(1 / 3))
    q2 = float(valid_values.quantile(2 / 3))
    for i, (_, row) in enumerate(points.iterrows(), start=1):
        geom = row.geometry
        value = pd.to_numeric(pd.Series([row[metal_column]]), errors="coerce").iloc[0]
        if geom is None or geom.is_empty or geom.geom_type != "Point" or pd.isna(value):
            continue
        label = str(row[site_column]) if site_column and pd.notna(row[site_column]) else f"Sample {i}"
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(geom.x), float(geom.y)]},
                         "properties": {"site": label, "value": float(value), "metal": metal_column,
                                        "longitude": round(float(geom.x), 6), "latitude": round(float(geom.y), 6)}})
    sample_json = {"type": "FeatureCollection", "features": features}

    def safe_json(obj):
        return json.dumps(obj, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    template = Path(__file__).with_name("maplibre_template.html").read_text(encoding="utf-8")
    replacements = {
        "__BOUNDARY__": safe_json(boundary_json),
        "__SAMPLES__": safe_json(sample_json),
        "__STYLES__": safe_json(STYLE_URLS),
        "__BOUNDS__": safe_json([[x0, y0], [x1, y1]]),
        "__METAL__": safe_json(metal_column),
        "__Q1__": safe_json(q1),
        "__Q2__": safe_json(q2),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    components.html(template, height=height, scrolling=False)
