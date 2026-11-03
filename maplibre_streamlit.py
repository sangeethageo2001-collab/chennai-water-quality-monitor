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
from risk_classes import classify

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
                  height: int = 650,
                  overlay_image: str | None = None,
                  overlay_bounds: list | None = None,
                  value_unit: str = "mg/L", raster_opacity: float = 0.70,
                  show_points: bool = True, show_boundary: bool = True,
                  point_color: str = "#FF0000",
                  default_basemap: str = "Satellite (Esri World Imagery)",
                  parameter_label: str | None = None,
                  parameter_group: str = "Heavy metals",
                  interpolation_method: str | None = None,
                  interpolation_range: tuple | None = None,
                  risk_threshold: float | None = None,
                  risk_threshold_direction: str = "Above",
                  risk_lower: float | None = None,
                  risk_reference: str | None = None,
                  risk_zone_image: str | None = None,
                  risk_zone_area_km2: dict | None = None,
                  moderate_fraction: float = 0.75,
                  risk_site_indices: list | None = None,
                  highlighted_indices: list | None = None,
                  ):
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
    risk_site_indices = set(risk_site_indices or [])
    highlighted_indices = set(highlighted_indices or [])
    for i, (idx, row) in enumerate(points.iterrows(), start=1):
        geom = row.geometry
        value = pd.to_numeric(pd.Series([row[metal_column]]), errors="coerce").iloc[0]
        if geom is None or geom.is_empty or geom.geom_type != "Point" or pd.isna(value):
            continue
        label = str(row[site_column]) if site_column and pd.notna(row[site_column]) else f"Sample {i}"
        observed_risk = "Unavailable"
        if risk_threshold is not None:
            observed_risk = str(classify([float(value)], risk_threshold,
                           risk_threshold_direction, risk_lower, moderate_fraction)[0])
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(geom.x), float(geom.y)]},
                         "properties": {"site": label, "value": float(value), "metal": metal_column,
                                        "longitude": round(float(geom.x), 6), "latitude": round(float(geom.y), 6),
                                        "predicted_flagged": bool(idx in risk_site_indices),
                                        "is_highlighted": bool(idx in highlighted_indices),
                                        "observed_class": observed_risk}})
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
        "__OVERLAY__": safe_json(overlay_image),
        "__OVERLAY_BOUNDS__": safe_json(overlay_bounds),
        "__UNIT__": safe_json(value_unit),
        "__RASTER_OPACITY__": safe_json(float(raster_opacity)),
        "__SHOW_POINTS__": safe_json(bool(show_points)),
        "__SHOW_BOUNDARY__": safe_json(bool(show_boundary)),
        "__POINT_COLOR__": safe_json(point_color),
        "__DEFAULT_BASEMAP__": safe_json(default_basemap),
        "__PARAMETER_LABEL__": safe_json(parameter_label or metal_column),
        "__PARAMETER_GROUP__": safe_json(parameter_group),
        "__INTERP_METHOD__": safe_json(interpolation_method),
        "__INTERP_RANGE__": safe_json(interpolation_range),
        "__RISK_THRESHOLD__": safe_json(risk_threshold),
        "__RISK_DIRECTION__": safe_json(risk_threshold_direction),
        "__RISK_REFERENCE__": safe_json(risk_reference),
        "__RISK_ZONE_IMAGE__": safe_json(risk_zone_image),
        "__RISK_ZONE_AREA__": safe_json(risk_zone_area_km2),
        "__MODERATE_FRACTION__": safe_json(moderate_fraction),
        "__HIGHLIGHT_ACTIVE__": safe_json(highlighted_indices is not None and len(highlighted_indices) > 0),
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    components.html(template, height=height, scrolling=False)
