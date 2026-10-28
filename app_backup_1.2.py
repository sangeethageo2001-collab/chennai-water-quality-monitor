from pathlib import Path

import geopandas as gpd
import pandas as pd
import plotly.express as px
import streamlit as st

from maplibre_streamlit import show_maplibre

st.set_page_config(page_title="Chennai Water Quality Monitor", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
DATA = BASE_DIR / "Data"

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
    boundary_path = DATA / "Chennai_new.shp"
    points_path = DATA / "Point_Data.shp"
    missing = [str(p) for p in (boundary_path, points_path) if not p.exists()]
    if missing:
        raise FileNotFoundError("Missing GIS shapefile(s): " + ", ".join(missing))
    boundary = gpd.read_file(boundary_path)
    points = gpd.read_file(points_path)
    if boundary.crs is None or points.crs is None:
        raise ValueError("Missing source CRS in boundary or sample points; specify the correct CRS in your GIS files.")
    return boundary.to_crs("EPSG:4326"), points.to_crs("EPSG:4326")


try:
    boundary, points = load_data()
except Exception as exc:
    st.error(f"Unable to load GIS data: {exc}")
    st.stop()

st.title("Chennai Water Quality Monitor")
st.caption("Heavy-metal sample explorer | Development version | MapLibre GL JS")
st.warning(
    "Dataset status: SYNTHETIC_NOT_MEASURED. Values are for software testing, "
    "not actual pollution measurements or a determination of water safety."
)

selected_metal = st.selectbox("Select heavy metal", list(METALS))
field = METALS[selected_metal]

if field not in points.columns:
    st.error(f"Required column {field} not found in Point_Data.shp")
    st.stop()

df = points.dropna(subset=["geometry"]).copy()
df = df[~df.geometry.is_empty].copy()
df[field] = pd.to_numeric(df[field], errors="coerce")
valid = df.dropna(subset=[field]).copy()
if valid.empty:
    st.error(f"No valid values found for {field}.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Sampling locations", len(points))
c2.metric("Valid values", len(valid))
c3.metric("Mean concentration", f"{valid[field].mean():.4f} mg/L")

st.subheader(f"{selected_metal} — Sampling Locations")
st.caption("Change the background inside the map using the MapLibre basemap dropdown.")
show_maplibre(
    boundary=boundary,
    samples=df,
    metal_column=field,
    site_column="Site_Name" if "Site_Name" in df.columns else None,
    height=650,
)
st.caption("Marker colours use relative terciles of available synthetic data, not water-safety thresholds. Basemap tiles and MapLibre JavaScript require internet access.")

st.subheader("Concentration by Sampling Site")
if "Site_ID" in valid.columns:
    fig = px.bar(
        valid,
        x="Site_ID", y=field,
        hover_name="Site_Name" if "Site_Name" in valid.columns else None,
        labels={"Site_ID": "Sampling site", field: "Concentration (mg/L)"},
        title=f"{selected_metal} concentrations",
    )
else:
    plot_df = valid.copy()
    plot_df["Sample"] = [f"Site {n}" for n in range(1, len(plot_df) + 1)]
    fig = px.bar(plot_df, x="Sample", y=field,
                 labels={"Sample": "Sampling site", field: "Concentration (mg/L)"},
                 title=f"{selected_metal} concentrations")
st.plotly_chart(fig, width="stretch")

st.subheader("Sample Data")
st.dataframe(valid.drop(columns="geometry"), width="stretch")
