
import streamlit as st
import geopandas as gpd
import pandas as pd
import plotly.express as px

from pathlib import Path

st.set_page_config(
    page_title="Chennai Water Quality Monitor",
    layout="wide"
)

DATA = Path("Data")

METALS = {
    "Lead (Pb)": "Pb_mg_L",
    "Cadmium (Cd)": "Cd_mg_L",
    "Chromium (Cr)": "Cr_mg_L",
    "Arsenic (As)": "As_mg_L",
    "Mercury (Hg)": "Hg_mg_L",
    "Nickel (Ni)": "Ni_mg_L",
    "Copper (Cu)": "Cu_mg_L",
    "Zinc (Zn)": "Zn_mg_L",
    "Iron (Fe)": "Fe_mg_L",
    "Manganese (Mn)": "Mn_mg_L",
}

@st.cache_data
def load_data():
    boundary = gpd.read_file(
        DATA / "Chennai_new.shp"
    ).to_crs("EPSG:4326")

    points = gpd.read_file(
        DATA / "Point_Data.shp"
    ).to_crs("EPSG:4326")

    return boundary, points

boundary, points = load_data()

st.title("Chennai Water Quality Monitor")
st.caption(
    "Heavy-metal sample explorer | Development version"
)

st.warning(
    "Dataset status: SYNTHETIC_NOT_MEASURED. "
    "Values are for software testing, not actual pollution "
    "measurements or a determination of water safety."
)

selected_metal = st.selectbox(
    "Select heavy metal",
    list(METALS.keys())
)

field = METALS[selected_metal]

df = points.dropna(
    subset=["geometry"]
).copy()

df[field] = pd.to_numeric(
    df[field], errors="coerce"
)

valid = df.dropna(subset=[field]).copy()

if valid.empty:
    st.error(f"No valid values found for {field}.")
    st.stop()

c1, c2, c3 = st.columns(3)

c1.metric("Sampling locations", len(points))
c2.metric("Valid values", len(valid))
c3.metric(
    "Mean concentration",
    f"{valid[field].mean():.4f} mg/L"
)

st.subheader(f"{selected_metal} — Sampling Locations")

# Create a self-contained map without external basemap tiles.
import folium
from streamlit.components.v1 import html as st_html

minx, miny, maxx, maxy = boundary.total_bounds

m = folium.Map(
    location=[
        (miny + maxy) / 2,
        (minx + maxx) / 2
    ],
    zoom_start=10,
    tiles=None
)

folium.GeoJson(
    boundary.to_json(),
    name="Chennai boundary",
    style_function=lambda feature: {
        "color": "#2457A7",
        "weight": 2,
        "fillColor": "#B8D5F0",
        "fillOpacity": 0.15
    }
).add_to(m)

q1 = valid[field].quantile(1 / 3)
q2 = valid[field].quantile(2 / 3)

def get_color(value):
    if value <= q1:
        return "green"
    if value <= q2:
        return "orange"
    return "red"

for _, row in df.iterrows():
    geom = row.geometry

    if geom is None or geom.is_empty:
        continue

    value = row[field]

    if pd.isna(value):
        color = "gray"
        concentration = "No data"
    else:
        color = get_color(float(value))
        concentration = f"{value:.6g} mg/L"

    popup = (
        f"Site: {row.get('Site_ID', 'Unknown')}<br>"
        f"Name: {row.get('Site_Name', 'Unknown')}<br>"
        f"{selected_metal}: {concentration}"
    )

    folium.CircleMarker(
        location=[geom.y, geom.x],
        radius=7,
        color=color,
        fill=True,
        fill_opacity=0.85,
        popup=folium.Popup(popup, max_width=280)
    ).add_to(m)

m.fit_bounds([[miny, minx], [maxy, maxx]])

st_html(m._repr_html_(), height=600, scrolling=False)

st.subheader("Concentration by Sampling Site")

fig = px.bar(
    valid,
    x="Site_ID",
    y=field,
    hover_name="Site_Name",
    labels={
        "Site_ID": "Sampling site",
        field: "Concentration (mg/L)"
    },
    title=f"{selected_metal} concentrations"
)

st.plotly_chart(fig, use_container_width=True)

st.subheader("Sample Data")

st.dataframe(
    valid.drop(columns="geometry"),
    use_container_width=True
)
