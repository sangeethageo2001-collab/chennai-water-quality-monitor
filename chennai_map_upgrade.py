"""Folium map helper for the Chennai Water Quality Monitor.

Input: GeoDataFrames boundary and samples with WGS84-compatible geometries,
and a numeric concentration field in samples.
"""
import html
import math

import folium
from folium.plugins import Fullscreen, MeasureControl, MousePosition
import pandas as pd


def build_water_quality_map(boundary, samples, metal_column, site_column=None):
    if metal_column not in samples.columns:
        raise ValueError(f"Missing metal column: {metal_column}")
    if boundary.empty:
        raise ValueError("Study boundary has no features")
    if samples.empty:
        raise ValueError("Sample layer has no features")
    if boundary.crs is None or samples.crs is None:
        raise ValueError("Both GeoDataFrames must have a defined CRS")

    boundary = boundary.to_crs(epsg=4326)
    samples = samples.to_crs(epsg=4326).copy()
    samples[metal_column] = pd.to_numeric(samples[metal_column], errors="coerce")
    samples = samples.loc[samples.geometry.notna() & samples[metal_column].notna()].copy()
    if samples.empty:
        raise ValueError("No valid sampling points for this heavy metal")

    vals = samples[metal_column]
    q1, q2 = [float(x) for x in vals.quantile([1/3, 2/3]).tolist()]

    def style_for(v):
        if v <= q1:
            return "#208a46", "Lower"
        if v <= q2:
            return "#f2a000", "Moderate"
        return "#db3838", "Higher"

    m = folium.Map(tiles=None, control_scale=True, zoom_control=True, prefer_canvas=True)
    folium.GeoJson(
        boundary.__geo_interface__, name="Chennai study boundary",
        style_function=lambda _: {"color": "#176ac2", "weight": 2.5, "fillColor": "#68a3dc", "fillOpacity": .07},
    ).add_to(m)

    layer = folium.FeatureGroup(name="Sampling locations", show=True)
    for idx, row in samples.iterrows():
        geom = row.geometry
        if geom.geom_type != "Point":
            continue
        val = float(row[metal_column])
        color, klass = style_for(val)
        name = str(row[site_column]) if site_column and site_column in samples.columns and pd.notna(row[site_column]) else f"Site {idx}"
        safe_name = html.escape(name)
        safe_metal = html.escape(str(metal_column))
        popup_html = (
            f"<div style='font-family:Arial;min-width:210px'>"
            f"<b>{safe_name}</b><hr style='margin:5px 0'>"
            f"<b>Metal:</b> {safe_metal}<br>"
            f"<b>Concentration:</b> {val:.5g} mg/L<br>"
            f"<b>Relative class:</b> {klass}<br>"
            f"<b>Latitude:</b> {geom.y:.6f}<br>"
            f"<b>Longitude:</b> {geom.x:.6f}<br>"
            f"<small>SYNTHETIC — NOT MEASURED</small></div>"
        )
        folium.CircleMarker(
            location=[geom.y, geom.x], radius=7, color="white", weight=1.5,
            fill=True, fill_color=color, fill_opacity=.92,
            tooltip=f"{name}: {val:.5g} mg/L",
            popup=folium.Popup(popup_html, max_width=300),
        ).add_to(layer)
    layer.add_to(m)

    bounds = boundary.total_bounds
    m.fit_bounds([[float(bounds[1]), float(bounds[0])], [float(bounds[3]), float(bounds[2])]], padding=(14, 14))
    folium.LayerControl(collapsed=False).add_to(m)
    Fullscreen(position="topright").add_to(m)
    MousePosition(position="bottomright", separator=" | ", prefix="Coordinates:", num_digits=5).add_to(m)

    legend = f"""
    <div style="position:fixed;bottom:25px;left:15px;z-index:9999;background:white;
    padding:10px 12px;border:1px solid #aab3bd;border-radius:6px;
    font-family:Arial;font-size:12px;box-shadow:0 2px 7px #0002;">
    <b>Relative concentration (mg/L)</b><br>
    <span style="color:#208a46">●</span> Lower: ≤ {q1:.5g}<br>
    <span style="color:#f2a000">●</span> Moderate: &gt; {q1:.5g} to ≤ {q2:.5g}<br>
    <span style="color:#db3838">●</span> Higher: &gt; {q2:.5g}<br>
    <small>Synthetic data — not water-safety classes</small>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend))
    return m
