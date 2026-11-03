"""Upload-only Streamlit GIS: multiple boundaries/CSV files, explicit Run, reviewed schema mapping."""
from pathlib import Path
import hashlib
import io
import re
import tempfile
import zipfile

import shapefile  # pyshp: geometry-only shapefile reading without .dbf
from pyproj import CRS
from shapely.geometry import shape

import geopandas as gpd
import pandas as pd
import plotly.express as px
import streamlit as st

from maplibre_streamlit import show_maplibre
from interpolation import create_surface
from piper_plot import render_piper_panel
from water_indices import calculate_indices, METAL_COLUMNS
from reference_limits import PRESET_NAME, SOURCE_URL, reference_dataframe, field_to_standard, BIS_ACCEPTABLE
from who_reference import WHO_NAME, WHO_SOURCE, WHO_GUIDELINES, who_standard, who_reference_dataframe
from usepa_reference import EPA_NAME, EPA_SOURCE, EPA_SECONDARY_SOURCE, EPA_LIMITS, epa_standard, epa_reference_dataframe, epa_limit_note
from risk_prediction import predict_site_risks
from risk_classes import classify
from report_export import make_report_pdf

st.set_page_config(page_title="AquaSpatial | Geospatial Water Quality Intelligence", layout="wide", initial_sidebar_state="expanded")

from auth import require_login
require_login()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ZIP_UNPACKED = 100 * 1024 * 1024
METALS = {
    "Lead (Pb)": "Pb_mg_L", "Cadmium (Cd)": "Cd_mg_L",
    "Chromium (Cr)": "Cr_mg_L", "Arsenic (As)": "As_mg_L",
    "Mercury (Hg)": "Hg_mg_L", "Nickel (Ni)": "Ni_mg_L",
    "Copper (Cu)": "Cu_mg_L", "Zinc (Zn)": "Zn_mg_L",
    "Iron (Fe)": "Fe_mg_L", "Manganese (Mn)": "Mn_mg_L",
}


@st.dialog("Piper Plot — Hydrochemical Facies", width="large")
def open_piper_plot(samples):
    """Display the Piper diagram and hydrochemical classification for uploaded records."""
    render_piper_panel(samples)


@st.dialog("Water Pollution Indices — WQI / HPI / WPI", width="large")
def open_indices_panel(samples, dataset_signature, workspace):
    st.caption("Automatically filled reference limits are a *drinking-water screening preset*, not limits inferred from your CSV. Check water type, units, species and edition before reporting.")
    method = st.selectbox("Index", ["WQI", "HPI", "WPI"], key=f"indices_method_{workspace}")
    preset = {"BIS": PRESET_NAME, "WHO": WHO_NAME, "USEPA": EPA_NAME}[workspace]
    st.info(f"Using {workspace} reference values. Switch frameworks to calculate the same index independently.")
    excluded = {"Latitude", "Longitude", "Site_ID", "Site_Name", "Source_File", "Dataset_Year", "Data_Status", "geometry"}
    candidates = [c for c in samples.columns if c not in excluded
                  and not str(c).startswith("__")
                  and pd.to_numeric(samples[c], errors="coerce").notna().any()]
    if method == "HPI":
        candidates = [c for c in candidates if c in METAL_COLUMNS]
    if not candidates:
        st.warning("No compatible numeric analytes found.")
        return

    has_ref = [c for c in candidates if (field_to_standard(c) if workspace == "BIS" else who_standard(c) if workspace == "WHO" else epa_standard(c))]
    default = has_ref if preset != "Manual — enter my own limits" else candidates[:min(5, len(candidates))]
    chosen = st.multiselect("Choose constituent columns", candidates, default=default,
                            key=f"chosen_{workspace}_{method}")
    if not chosen:
        st.info("Select parameters to continue.")
        return

    if workspace in ("BIS", "WHO", "USEPA"):
        reference_defaults, omitted = ({"BIS": reference_dataframe, "WHO": who_reference_dataframe, "USEPA": epa_reference_dataframe}[workspace])(chosen, method)
        if omitted:
            st.warning("No applicable automatic limit for: " + ", ".join(omitted) +
                       ". They are excluded; choose Manual if you need to provide suitable limits.")
        if reference_defaults.empty:
            st.error("None of the chosen parameters has a matching preset standard.")
            return
    else:
        reference_defaults = pd.DataFrame([{"Parameter": c, "Standard": None, "Ideal": None,
                                           "Lower": None, "Weight": None} for c in chosen])

    st.caption("Units: mg/L unless otherwise noted; pH is unitless. Drinking-water reference values must not be applied to unrelated surface-water uses. EPA secondary guidelines are non-enforceable federal aesthetic recommendations.")
    st.caption("Edit a value below if your official reference source or study method requires it. Blank Weight uses 1/Standard.")
    ref_key = f"reference_{method}_{workspace.lower()}_{hash(tuple(chosen))}"
    reference = st.data_editor(reference_defaults, hide_index=True, use_container_width=True,
                               disabled=["Parameter"], num_rows="fixed", key=ref_key)
    if preset == PRESET_NAME:
        st.caption(f"Source: BIS IS 10500:2012 acceptable-limit screening. {SOURCE_URL}")
    elif workspace == "WHO":
        st.caption(f"Source: WHO Guidelines for Drinking-water Quality (2022), selected guideline values. {WHO_SOURCE}. Mercury is NOT automatically populated because the CSV may report total rather than inorganic mercury.")
    elif workspace == "USEPA":
        st.caption(f"Source: US EPA primary regulations: {EPA_SOURCE}; secondary guidance: {EPA_SECONDARY_SOURCE}. Lead/copper are treatment-technique/action-level analytes and excluded from automatic numeric-MCL screening. Verify mercury species, nitrate units and EPA rule effective dates.")
        if any(epa_standard(c) and EPA_LIMITS[epa_standard(c)][4] == "Secondary" for c in reference["Parameter"]):
            st.warning("One or more EPA reference values are secondary non-enforceable aesthetic guidelines, not health-based MCLs.")
    if any(c in reference['Parameter'].values for c in ("Cr_mg_L", "Hg_mg_L")):
        chemistry_confirmed = st.checkbox("I have checked chromium/mercury analyte identity and units against the reference method.", value=False)
    else:
        chemistry_confirmed = True
    if method == "WPI":
        st.info("WPI here is a *defined mean normalized ratio* (Q/100), not a universal official index. A BIS limit preset does not make the WPI formula regulatory.")
    elif method == "WQI":
        st.caption("Weighted arithmetic WQI. pH uses the two-sided range where available. DO is not assigned a drinking-water reference automatically.")
    else:
        st.caption("Heavy Metal Pollution Index: weighted mean of 100 × |C − Ideal| / (Standard − Ideal).")
    st.warning("These indices do not establish water potability. Your uploaded values have not been independently verified; synthetic data remain synthetic.")
    if st.button("Calculate and show on map", type="primary", key=f"apply_index_{workspace}_{method}"):
        try:
            if not chemistry_confirmed:
                raise ValueError("Confirm analyte identity before using the chromium or mercury preset.")
            score, details = calculate_indices(samples, method, reference)
            if score.notna().sum() < 3:
                raise ValueError("Need at least three complete sample sites to show a spatial index map")
            result_key = f"{method} ({workspace} screening)"
            saved = st.session_state.setdefault("standard_index_results", {})
            saved[f"{workspace}:{method}"] = {
                "signature": dataset_signature, "field": "__WaterIndexScore",
                "label": result_key, "method": method, "score": score.to_list(),
                "table": details, "configuration": reference,
                "source": preset, "workspace": workspace,
            }
            st.session_state[f"selected_index_{workspace}"] = method
            st.session_state[f"control_group_{workspace}"] = "Pollution indices"
            st.rerun()
        except Exception as exc:
            st.error(f"Could not calculate index: {exc}")


def keyname(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


ALIASES = {
    "Site_ID": ["siteid", "sampleid", "stationid", "locationid", "pointid", "id", "samplecode"],
    "Site_Name": ["sitename", "stationname", "locationname", "samplinglocation", "place", "site", "name"],
    "Latitude": ["latitude", "lat", "latdd", "ycoordinate", "ycoord", "gpslat", "northingwgs84"],
    "Longitude": ["longitude", "long", "lon", "lng", "longdd", "xcoordinate", "xcoord", "gpslon", "eastingwgs84"],
    "Temperature_C": ["temperaturec", "temperature", "temperatur", "tempc", "watertemp", "watertemperature", "temp", "tempdegc"],
    "Parameter": ["parameter", "analyte", "metal", "indicator", "testname", "parametername"],
    "Value": ["value", "result", "reading", "concentration", "measurement", "resultvalue"],
}
SYMBOLS = {"Pb": "Pb_mg_L", "Cd": "Cd_mg_L", "Cr": "Cr_mg_L", "As": "As_mg_L", "Hg": "Hg_mg_L", "Ni": "Ni_mg_L", "Cu": "Cu_mg_L", "Zn": "Zn_mg_L", "Fe": "Fe_mg_L", "Mn": "Mn_mg_L"}
NAMES = {"lead": "Pb", "cadmium": "Cd", "chromium": "Cr", "arsenic": "As", "mercury": "Hg", "nickel": "Ni", "copper": "Cu", "zinc": "Zn", "iron": "Fe", "manganese": "Mn"}


def guess_column(columns, wanted):
    normalized = {keyname(c): c for c in columns}
    for name in [wanted] + ALIASES.get(wanted, []):
        if keyname(name) in normalized:
            return normalized[keyname(name)]
    return None


def standard_measure(column):
    key = keyname(column)
    if key in [keyname(x) for x in ALIASES["Temperature_C"]] or key == "temperaturec":
        return "Temperature_C"
    physical = {
        "ph": "pH", "phvalue": "pH", "waterph": "pH",
        "tds": "TDS_mg_L", "tdsmgl": "TDS_mg_L", "totaldissolvedsolids": "TDS_mg_L",
        "ec": "EC_uS_cm", "ecuscm": "EC_uS_cm", "electricalconductivity": "EC_uS_cm",
        "turbidity": "Turbidity_NTU", "turbidityntu": "Turbidity_NTU",
        "do": "DO_mg_L", "domgl": "DO_mg_L", "dissolvedoxygen": "DO_mg_L",
        "bod": "BOD_mg_L", "bodmgl": "BOD_mg_L",
        "cod": "COD_mg_L", "codmgl": "COD_mg_L",
        "salinity": "Salinity", "salinityppt": "Salinity",
        "chloridem": "Chloride_mg_L", "chloridemgl": "Chloride_mg_L",
        "sulphatem": "Sulphate_mg_L", "sulphatemgl": "Sulphate_mg_L",
        "nitratemg": "Nitrate_mg_L", "nitratemgl": "Nitrate_mg_L",
        "fluoridem": "Fluoride_mg_L", "fluoridemgl": "Fluoride_mg_L",
        "alkalinity": "Alkalinity_mg_L", "totalhard": "Total_Hardness_mg_L",
        "totalhardness": "Total_Hardness_mg_L",
        "turbiditym": "Turbidity_NTU",
    }
    if key in physical:
        return physical[key]
    if key in [keyname(x) for x in METALS.values()]:
        return next(v for v in METALS.values() if keyname(v) == key)
    for symbol, target in SYMBOLS.items():
        k = symbol.lower()
        if key in (k, k + "mgl", k + "ppm", k + "concentration", k + "mgperlitre", k + "mgperl"):
            return target
    for word, sym in NAMES.items():
        if key in (word, word + "mgl", word + "ppm", word + "concentration"):
            return SYMBOLS[sym]
    return None


@st.cache_data(show_spinner=False)
def read_tabular(blob, filename):
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError("File exceeds 25 MB")
    encodings = ("utf-8-sig", "utf-16", "cp1252", "latin-1")
    errors = []
    for enc in encodings:
        try:
            data = pd.read_csv(io.BytesIO(blob), sep=None, engine="python", encoding=enc, dtype=str, on_bad_lines="error")
            if len(data.columns) == 1:
                # Try common alternate separators, especially for unusual header encodings
                for delimiter in (",", ";", "\t", "|"):
                    candidate = pd.read_csv(io.BytesIO(blob), sep=delimiter, encoding=enc, dtype=str)
                    if len(candidate.columns) > len(data.columns):
                        data = candidate
            data.columns = [str(c).strip().lstrip("\ufeff") for c in data.columns]
            data = data.dropna(how="all")
            if data.empty:
                raise ValueError("CSV has no data rows")
            if len(set(data.columns)) != len(data.columns):
                raise ValueError("Duplicate column headers")
            return data
        except Exception as exc:
            errors.append(f"{enc}: {str(exc)[:80]}")
    raise ValueError("Cannot parse CSV. Check encoding, delimiter and rows. " + " | ".join(errors[:2]))


def number_series(values):
    # Supports dot-decimal, comma-decimal, and thousands-separated numerics.
    s = values.astype("string").str.strip().str.replace("\u00a0", "", regex=False)
    if s.str.contains(",", regex=False).any():
        both = s.str.contains(r"\d[,.]\d", regex=True)
        sample = s[both].dropna().head(20)
        if len(sample) and sample.str.contains(r"\d+,\d+$", regex=True).mean() >= .75 and not sample.str.contains(r"\.", regex=True).any():
            s = s.str.replace(",", ".", regex=False)
        else:
            s = s.str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parse_boundary(upload):
    """Read a polygon GeoJSON or shapefile ZIP; DBF is optional for geometry-only boundaries."""
    blob = upload.getvalue()
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError("Boundary exceeds 25 MB")

    if upload.name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > 60 or sum(m.file_size for m in members) > MAX_ZIP_UNPACKED:
                raise ValueError("ZIP exceeds extraction limit")

            # Accept components inside one parent folder, plus optional metadata.
            # Do not extract paths from untrusted ZIP archives to the filesystem.
            components = {}
            for member in members:
                p = Path(member.filename.replace("\\", "/"))
                if p.is_absolute() or ".." in p.parts or len(p.parts) > 3:
                    raise ValueError("ZIP contains an unsafe or overly nested path")
                if p.suffix.lower() not in {".shp", ".shx", ".dbf", ".prj", ".cpg", ".xml", ".sbn", ".sbx"}:
                    continue
                key = p.name.lower()
                if key in components:
                    raise ValueError(f"Duplicate component filename: {p.name}")
                components[key] = archive.read(member)

            shp_names = [name for name in components if name.endswith(".shp")]
            if len(shp_names) != 1:
                raise ValueError("Each ZIP must contain exactly one .shp boundary file")
            base = shp_names[0][:-4]
            prj_data = components.get(base + ".prj")
            if prj_data is None:
                raise ValueError("Missing matching .prj: boundary CRS cannot be determined")
            try:
                crs = CRS.from_wkt(prj_data.decode("utf-8-sig"))
            except Exception as exc:
                raise ValueError(f"Invalid shapefile CRS in .prj: {exc}") from exc

            shp_data = components[base + ".shp"]
            shx_data = components.get(base + ".shx")
            dbf_data = components.get(base + ".dbf")

            # Read polygon geometry directly. No attribute table is necessary.
            kwargs = {"shp": io.BytesIO(shp_data)}
            if shx_data is not None:
                kwargs["shx"] = io.BytesIO(shx_data)
            if dbf_data is not None:
                kwargs["dbf"] = io.BytesIO(dbf_data)
            try:
                with shapefile.Reader(**kwargs) as reader:
                    geometries = [shape(record.__geo_interface__) for record in reader.shapes()]
            except Exception as exc:
                raise ValueError(f"Could not read shapefile geometry: {exc}") from exc
            if not geometries:
                raise ValueError("Shapefile contains no geometry")
            frame = gpd.GeoDataFrame(geometry=geometries, crs=crs)
    else:
        # GeoJSON coordinates are assumed WGS84 by GeoPandas/GeoJSON convention.
        frame = gpd.read_file(io.BytesIO(blob), driver="GeoJSON")

    if frame.crs is None:
        raise ValueError("Boundary has no CRS. Include .prj or WGS84 GeoJSON")
    frame = frame.to_crs("EPSG:4326")
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if frame.empty or not frame.geom_type.isin(["Polygon", "MultiPolygon"]).all():
        raise ValueError("Boundary must contain Polygon/MultiPolygon geometries")
    if not frame.is_valid.all():
        raise ValueError("Invalid polygons. Repair geometry before uploading")
    return frame


def normalize_one_csv(df, mapping, filename, file_no):
    lat_field, lon_field, id_field, name_field = mapping
    lat, lon = number_series(df[lat_field]), number_series(df[lon_field])
    good = lat.between(-90, 90) & lon.between(-180, 180)
    if not good.any():
        raise ValueError("No valid WGS84 latitude/longitude pairs. Choose correct columns; projected metres are not supported")
    copy = df.loc[good].copy()
    copy["Latitude"], copy["Longitude"] = lat[good], lon[good]
    if id_field is not None:
        copy["Site_ID"] = df.loc[good, id_field].astype("string").fillna("").str.strip()
    else:
        copy["Site_ID"] = [f"F{file_no}-{i:04d}" for i in range(1, len(copy) + 1)]
    if name_field is not None:
        copy["Site_Name"] = df.loc[good, name_field].astype("string").fillna(copy["Site_ID"])
    else:
        copy["Site_Name"] = copy["Site_ID"]
    # Long-form datasets: one parameter and one measurement per row.
    # Convert to wide format for the GIS interpolation engine.
    param_field = guess_column(df.columns, "Parameter")
    value_field = guess_column(df.columns, "Value")
    if param_field is not None and value_field is not None and param_field != value_field:
        copy["__param"] = df.loc[good, param_field].astype(str).map(
            lambda p: standard_measure(p) or str(p).strip()
        )
        copy["__value"] = number_series(df.loc[good, value_field])
        copy = copy.pivot_table(
            index=["Site_ID", "Site_Name", "Latitude", "Longitude"],
            columns="__param", values="__value", aggfunc="mean"
        ).reset_index()
        copy.columns.name = None
        numeric_cols = [c for c in copy.columns if c not in {"Site_ID", "Site_Name", "Latitude", "Longitude"}]
        copy["Source_File"] = filename
        frame = gpd.GeoDataFrame(copy, geometry=gpd.points_from_xy(copy.Longitude, copy.Latitude), crs="EPSG:4326")
        return frame, len(df) - int(good.sum()), numeric_cols
    protected = {lat_field, lon_field, id_field, name_field, "Latitude", "Longitude", "Site_ID", "Site_Name", "Dataset_Year", "Data_Status"}
    used = []
    for col in df.columns:
        if col in protected:
            continue
        standard = standard_measure(col)
        if standard:
            numeric = number_series(df.loc[good, col])
            if standard in copy and standard != col:
                copy[standard] = number_series(copy[standard]).combine_first(numeric)
            else:
                copy[standard] = numeric
            used.append(standard)
        else:
            # Retain other numeric parameters with their original names and generic units.
            numeric = number_series(df.loc[good, col])
            if numeric.notna().sum() and numeric.notna().sum() >= max(1, int(.6 * len(copy))):
                if col not in protected and col not in ("Latitude", "Longitude"):
                    copy[col] = numeric
                    used.append(col)
    copy["Source_File"] = filename
    frame = gpd.GeoDataFrame(copy, geometry=gpd.points_from_xy(copy.Longitude, copy.Latitude), crs="EPSG:4326")
    return frame, len(df) - len(frame), used



# ----------------------------------------------------------
# Single-screen dashboard shell (no global page scrolling)
# ----------------------------------------------------------
import streamlit.components.v1 as components

st.markdown("""<style>
/* Aqua Ocean | UI only: preserves scientific risk-map colours */
:root {--aqua-navy:#073B5D;--aqua-blue:#087EAC;--aqua-teal:#16B8C4;--aqua-ice:#E8F7FB;--aqua-white:#FFFFFF;--aqua-text:#334155;}
html,body,[data-testid="stAppViewContainer"],.stApp {min-height:100vh;color:var(--aqua-text);}
[data-testid="stMain"] {min-height:100vh;overflow-y:auto!important;background:linear-gradient(145deg,#f8fdff 0%,#e8f7fb 56%,#e1f4fa 100%);}
[data-testid="stMainBlockContainer"] {padding:2.2rem .7rem .4rem!important;max-width:100%!important;}
/* Keep the sidebar toggle usable, including when collapsed */
[data-testid="stHeader"] {display:block!important;visibility:visible!important;background:transparent!important;z-index:1000!important;}
[data-testid="stSidebarCollapsedControl"],[data-testid="stSidebar"] {visibility:visible!important;}
#MainMenu,footer {display:none!important;}
[data-testid="stSidebar"] {background:linear-gradient(180deg,#d9f3fa,#c9eaf4)!important;border-right:1px solid #b6dce8;}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {overflow-y:auto!important;}
[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3 {color:var(--aqua-navy)!important;}
[data-testid="stVerticalBlock"] {gap:.35rem!important;}
[data-testid="stHorizontalBlock"] {gap:.6rem!important;}
/* Strong water-themed heading hierarchy */
[data-testid="stMain"] h1 {color:var(--aqua-navy)!important;font-size:clamp(1.35rem,2vw,2rem)!important;font-weight:800!important;letter-spacing:-.03em!important;line-height:1.12!important;margin:.1rem 0 .24rem!important;padding-left:.75rem!important;border-left:5px solid var(--aqua-teal)!important;}
[data-testid="stMain"] h2,[data-testid="stMain"] h3,[data-testid="stMain"] h4 {color:var(--aqua-navy)!important;font-weight:750!important;}
[data-testid="stMain"] h4 {border-left:4px solid var(--aqua-teal);padding-left:.55rem;margin:.25rem 0 .35rem!important;}
[data-testid="stMain"] strong {color:#075c7d;}
[data-testid="stMetric"] {background:rgba(255,255,255,.96)!important;border:1px solid #b8e1eb!important;border-top:3px solid #16b8c4!important;border-radius:12px!important;padding:.35rem .65rem!important;box-shadow:0 3px 12px #073b5d0b;}
[data-testid="stMetricLabel"] p {font-size:.76rem!important;color:#466b7d!important;}
[data-testid="stMetricValue"] {font-size:1.35rem!important;color:var(--aqua-navy)!important;font-weight:750!important;}
[data-testid="stSelectbox"] label p,[data-testid="stRadio"] label p {font-size:.8rem!important;color:var(--aqua-navy)!important;}
[data-testid="stButton"] button[kind="primary"],.stButton button[kind="primary"] {background:var(--aqua-blue)!important;border-color:var(--aqua-blue)!important;color:white!important;}
.stButton button,.stDownloadButton button {border-radius:9px!important;border-color:#afd8e5!important;}
.stButton button:hover,.stDownloadButton button:hover {border-color:var(--aqua-teal)!important;}
[data-baseweb="select"]>div {border-radius:9px!important;border-color:#b4dae6!important;}
[data-testid="stExpander"] {background:rgba(255,255,255,.85)!important;border:1px solid #c6e6ef!important;border-radius:10px!important;}
[data-testid="stAlert"] {padding:.35rem .6rem!important;}
iframe[title="streamlit.components.v1.html"] {display:block!important;width:100%!important;border-radius:13px!important;box-shadow:0 4px 18px #073b5d16;}
/* Keep dialog, sidebar and select menus usable on smaller screens */
@media(max-height:750px) {iframe[title="streamlit.components.v1.html"] {min-height:390px!important;}}
@media(max-width:900px) {[data-testid="stMain"] {overflow:auto!important;}}

/* Authentic GIS workspace: sticky clean header, compact controls, accessible map */
[data-testid="stMainBlockContainer"] {padding-top:1.1rem!important;}
[data-testid="stMain"] {background:linear-gradient(160deg,#f7fcff,#edf8fb 65%,#e7f5f9)!important;}
[data-testid="stMain"] h1 {font-size:1.65rem!important;}
[data-testid="stMain"] h4 {font-size:1rem!important;}
[data-testid="stMetric"] {min-height:66px!important;}
[data-testid="stMetricValue"] {font-size:1.22rem!important;}
[data-testid="stSidebar"] {min-width:200px!important;}
@media(min-width:1280px) {[data-testid="stMainBlockContainer"] {padding-bottom:.2rem!important;}}

/* Reference-style Aqua Ocean professional design system */
:root{--ocean:#073B5D;--water:#087EAC;--aqua:#16B8C4;--ice:#E8F7FB;--divider:#B7E2EB;}
[data-testid="stMain"]{background:linear-gradient(165deg,#E8F7FB 0%,#f4fcff 58%,#def3f9 100%)!important;}
[data-testid="stMainBlockContainer"]{max-width:100%!important;padding:1.1rem .95rem 1rem!important;}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#f9fdff 0%,#e8f7fb 82%,#c6eef5 100%)!important;min-width:235px!important;border-right:1px solid #B7E2EB!important;}
[data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding:.8rem .7rem!important;}
[data-testid="stHeader"]{background:transparent!important;visibility:visible!important;}
[data-testid="stSidebarCollapsedControl"]{visibility:visible!important;display:flex!important;}
/* Branded header, with no imaginary real-world values. */
.aqua-hero{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:.4rem;padding:.4rem .7rem .4rem 0;border-bottom:2px solid #b7e2eb;}
.aqua-hero .heading{display:flex;gap:10px;align-items:center;}
.aqua-hero h1{border:none!important;padding:0!important;margin:0!important;color:#073B5D!important;font-weight:850!important;font-size:clamp(1.25rem,2.2vw,2.1rem)!important;line-height:1.13!important;}
.aqua-hero .subtitle{font-size:.78rem;color:#087EAC;margin-top:3px;}
.aqua-watermark{font-size:.7rem;color:#3e7286;white-space:nowrap;}
.aqua-side-brand{border-radius:13px;padding:15px 12px;margin:0 0 9px;background:linear-gradient(120deg,#073B5D,#087EAC);color:#fff!important;font-size:1.02rem;font-weight:800;line-height:1.45;}
.aqua-nav-caption{letter-spacing:.13em;text-transform:uppercase;font-size:.65rem;color:#3d7d91;font-weight:800;margin:12px 0 2px;}
.aqua-section{background:linear-gradient(90deg,#073B5D,#087EAC);border-radius:8px;padding:8px 12px;color:#fff!important;font-weight:750;font-size:1rem;margin:.2rem 0 .35rem;display:flex;align-items:center;justify-content:space-between;gap:8px;}
.aqua-control-head{background:linear-gradient(90deg,#087EAC,#16B8C4);border-radius:8px;padding:8px 12px;color:white!important;font-size:1rem;font-weight:750;margin-bottom:.4rem;}
.aqua-panel-note{color:#42768a;font-size:.69rem;line-height:1.3;}
[data-testid="stMetric"]{background:#fff!important;border:1px solid #B7E2EB!important;border-top:3px solid #16B8C4!important;border-radius:12px!important;box-shadow:0 3px 9px #073b5d0a!important;min-height:77px!important;padding:.5rem .7rem!important;}
[data-testid="stMetricValue"]{font-size:1.38rem!important;color:#073B5D!important;}
[data-testid="stMetricLabel"] p{color:#31687c!important;font-weight:650!important;}
[data-testid="stExpander"], [data-testid="stVerticalBlockBorderWrapper"] > div{border-color:#B7E2EB!important;}
[data-testid="stButton"] button[kind="primary"],.stButton button[kind="primary"]{background:#087EAC!important;border-color:#087EAC!important;color:white!important;}
[data-testid="stMain"] h4{border-left:4px solid #16B8C4!important;padding-left:8px!important;color:#073B5D!important;}
[data-testid="stRadio"] label p{font-size:.83rem!important;}
iframe[title="streamlit.components.v1.html"]{border:1px solid #B7E2EB!important;border-radius:10px!important;box-shadow:0 4px 14px #073b5d12!important;}
@media(min-width:1300px){[data-testid="stMainBlockContainer"]{padding-left:1.15rem!important;padding-right:1.15rem!important;}}
@media(max-width:950px){.aqua-watermark{display:none;}.aqua-hero h1{font-size:1.35rem!important;}}
</style>""", unsafe_allow_html=True)

# MapLibre at startup: a real interactive basemap, but no invented observations.
def show_empty_map(height=550):
    html = r"""<!doctype html><html><head><meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1"/>
    <link href="https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.css" rel="stylesheet" />
    <style>html,body,#map{height:100%;width:100%;margin:0}#map{position:absolute;inset:0}
    .notice{position:absolute;top:12px;left:12px;max-width:340px;background:#fff;
    color:#263342;padding:12px 15px;border-radius:9px;font:13px Arial;box-shadow:0 2px 10px #0003}
    </style></head><body><div id="map"></div><div class="notice"><b>Map ready</b><div style="margin-top:6px">Upload a boundary and sampling CSV, then press Run Analysis. No data have been loaded.</div></div>
    <script type="module">import * as ml from 'https://unpkg.com/maplibre-gl@6.16.0/dist/maplibre-gl.mjs';
    const map=new ml.Map({container:'map',style:{version:8,sources:{'esri':{type:'raster',tiles:['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],tileSize:256,attribution:'Imagery © Esri and contributors'}},layers:[{id:'satellite',type:'raster',source:'esri'}]},center:[80.27,13.08],zoom:9});
    map.addControl(new ml.NavigationControl(),'top-right');
    map.addControl(new ml.FullscreenControl(),'top-right');
    </script></body></html>"""
    components.html(html, height=height, scrolling=False)

PHYSICAL = {
    "pH": ("pH", ""),
    "TDS_mg_L": ("TDS", "mg/L"),
    "EC_uS_cm": ("EC", "µS/cm"),
    "Temperature_C": ("Temperature", "°C"),
    "Turbidity_NTU": ("Turbidity", "NTU"),
    "DO_mg_L": ("Dissolved Oxygen", "mg/L"),
    "BOD_mg_L": ("BOD", "mg/L"),
    "COD_mg_L": ("COD", "mg/L"),
}

st.sidebar.markdown('<div class="aqua-side-brand">AquaSpatial</div>', unsafe_allow_html=True)
st.sidebar.markdown('<div class="aqua-nav-caption">DATA MANAGEMENT</div>', unsafe_allow_html=True)
st.sidebar.header("GIS Data Management")
st.sidebar.caption("Upload study boundaries and one or more CSV files to analyze water quality.")
boundary_uploads = st.sidebar.file_uploader("Polygon boundary (GeoJSON / ZIP)", type=["geojson", "json", "zip"], accept_multiple_files=True)
csv_uploads = st.sidebar.file_uploader("Water quality CSV files", type=["csv"], accept_multiple_files=True)
st.sidebar.download_button("Download sample CSV headers", "Site_ID,Site_Name,Latitude,Longitude,pH,TDS_mg_L,EC_uS_cm,Temperature_C,Pb_mg_L\n", file_name="water_quality_template.csv", mime="text/csv")
source_status = st.sidebar.selectbox("Data status (user-declared)", ["Synthetic/test data", "Unverified observations", "User-verified laboratory observations"])
if source_status == "User-verified laboratory observations":
    st.sidebar.warning("User-verified does not mean independently audited. Document your laboratory QA/QC and chain of custody.")
with st.sidebar.expander("Data provenance & quality", expanded=False):
    st.caption("Use measured values, sample date, analytical method, units and laboratory QA/QC for defensible scientific reporting.")
    st.caption("Dataset status is declared by the uploader. The system has not authenticated laboratory records or sample collection.")
    st.caption("Out-of-range coordinates and missing parameter measurements are excluded from applicable calculations and flagged in coverage summaries.")

parsed, mappings, csv_errors = [], [], []
if csv_uploads:
    with st.sidebar.expander("CSV columns and preview", expanded=False):
        for idx, upload in enumerate(csv_uploads):
            try:
                raw = read_tabular(upload.getvalue(), upload.name)
                columns = list(raw.columns)
                guesses = [guess_column(columns, name) for name in ("Latitude", "Longitude", "Site_ID", "Site_Name")]
                st.caption(f"{upload.name} · {len(raw)} records")
                options = ["— Select —"] + columns
                choices = []
                for tag, guess in zip(("Latitude", "Longitude", "Site ID", "Site Name"), guesses):
                    selection = st.selectbox(tag, options, index=options.index(guess) if guess in columns else 0, key=f"map_{idx}_{tag}")
                    choices.append(None if selection == "— Select —" else selection)
                st.dataframe(raw.head(3), width="stretch", height=110)
                parsed.append((upload, raw))
                mappings.append(tuple(choices))
            except Exception as exc:
                csv_errors.append(f"{upload.name}: {exc}")

fingerprint = repr(([(u.name, hashlib.sha256(u.getvalue()).hexdigest()) for u in (boundary_uploads or [])+(csv_uploads or [])], mappings, source_status))
run_clicked = st.sidebar.button("▶ Run Analysis", type="primary", width="stretch")
if run_clicked:
    st.session_state["run_fingerprint"] = fingerprint
running = (st.session_state.get("run_fingerprint") == fingerprint)

boundary, points, error_message = None, None, None
if running and boundary_uploads and parsed and not csv_errors and len(parsed) == len(csv_uploads):
    try:
        parts = [parse_boundary(up) for up in boundary_uploads]
        boundary = gpd.GeoDataFrame(pd.concat(parts,ignore_index=True), crs="EPSG:4326")
        frames=[]
        for idx, ((up,raw), mapping) in enumerate(zip(parsed,mappings),1):
            if mapping[0] is None or mapping[1] is None or mapping[0]==mapping[1]:
                raise ValueError(f"{up.name}: choose separate Latitude and Longitude columns under CSV columns and preview")
            frame,dropped,fields=normalize_one_csv(raw,mapping,up.name,idx)
            frames.append(frame)
        points=gpd.GeoDataFrame(pd.concat(frames,ignore_index=True),crs="EPSG:4326")
        if points.empty: raise ValueError("No valid sampling records")
    except Exception as exc:
        error_message = str(exc)
        boundary,points=None,None
elif run_clicked and not boundary_uploads:
    error_message="Upload at least one boundary before running analysis"
elif run_clicked and not csv_uploads:
    error_message="Upload at least one sampling CSV before running analysis"
elif csv_errors:
    error_message=" | ".join(csv_errors)

# Main viewport: compact toolbar and metrics, plus a map that is always visible.
st.markdown("""<div class="aqua-hero"><div class="heading"><div><h1>AquaSpatial</h1><div class="subtitle">Geospatial Water Quality Intelligence</div></div></div><div class="aqua-watermark">AQUASPATIAL · GIS ANALYTICS</div></div>""", unsafe_allow_html=True)

# Two fully independent standard-specific analysis workspaces.
workspace = st.segmented_control(
    "Reference framework",
    options=["BIS", "WHO", "USEPA"],
    format_func=lambda v: {
        "BIS": "BIS Standard",
        "WHO": "WHO Standard",
        "USEPA": "US EPA Standard",
    }[v],
    default="BIS",
    selection_mode="single",
    key="selected_standard_workspace",
)
# Keep one framework selected for consistent index/risk calculations.
if workspace is None:
    workspace = "BIS"
workspace_preset = {"BIS": PRESET_NAME, "WHO": WHO_NAME, "USEPA": EPA_NAME}[workspace]
st.caption(f"{workspace_preset} · Drinking-water screening only · Risk bands are application-defined, not official BIS/WHO/EPA classifications.")
# Reserve a KPI row ahead of the map and analysis controls; fill it after calculations.
kpi_row = st.empty()

# Keep every {standard}:{index} result separately, and invalidate on data changes.
all_index_results = st.session_state.setdefault("standard_index_results", {})
for saved_key in list(all_index_results):
    item = all_index_results[saved_key]
    if points is None or item.get("signature") != fingerprint or len(item.get("score", [])) != len(points):
        all_index_results.pop(saved_key, None)
selected_index = st.session_state.get(f"selected_index_{workspace}", "WQI")
active_index = all_index_results.get(f"{workspace}:{selected_index}")
if points is not None and active_index is not None:
    points["__WaterIndexScore"] = pd.Series(active_index["score"], index=points.index)

parameters={}
if points is not None:
    for name,col in METALS.items():
        if col in points and number_series(points[col]).notna().any():
            parameters[name]=(col,"mg/L")
    for col,(name,unit) in PHYSICAL.items():
        if col in points and number_series(points[col]).notna().any():
            parameters[name]=(col,unit)
    ignored={"Latitude","Longitude","Site_ID","Site_Name","Source_File","geometry","Dataset_Year","Data_Status"}
    ignored.update(METALS.values());ignored.update(PHYSICAL)
    for col in points.columns:
        if col in ignored or str(col).startswith("__"):continue
        values=number_series(points[col]) if col!="geometry" else pd.Series(dtype=float)
        if values.notna().any():parameters[col]=(col,"unit unspecified")

if points is not None and active_index is not None and "__WaterIndexScore" in points:
    parameters[active_index["label"]] = ("__WaterIndexScore", "index")

# ----------------------------------------------------------
# Parameter groups — each selection controls the SAME map,
# summary statistics, interpolation, and data preview.
# ----------------------------------------------------------
GROUPS = ["Heavy metals", "Chemical parameters", "Physical parameters", "Pollution indices"]

GROUP_POINT_COLORS = {
    "Heavy metals": "#FF0000",
    "Chemical parameters": "#0066FF",
    "Physical parameters": "#FF9800",
    "Pollution indices": "#808080",
}

PHYSICAL_FIELDS = {"pH", "TDS_mg_L", "EC_uS_cm", "Temperature_C", "Turbidity_NTU", "DO_mg_L", "Salinity"}

# Chemistry names come from uploaded data; any other numeric water chemistry
# field is listed under Chemical parameters instead of being discarded.
def group_for(label, column):
    if column == "__WaterIndexScore":
        return "Pollution indices"
    if column in METALS.values():
        return "Heavy metals"
    if column in PHYSICAL_FIELDS:
        return "Physical parameters"
    return "Chemical parameters"

# WQI/HPI/WPI are always shown as analysis choices. A map is only displayed
# after calculation using validated reference settings, never fabricated.
index_names = ["WQI", "HPI", "WPI"]
if f"control_group_{workspace}" not in st.session_state:
    st.session_state[f"control_group_{workspace}"] = GROUPS[0]

left, right = st.columns([4.7, 2.0], gap="small")
with right:
    with st.container(border=True):
        st.markdown('<div class="aqua-control-head">⚗ Analysis &amp; Visualization</div>', unsafe_allow_html=True)
        group = st.radio("Parameter group", GROUPS, key=f"control_group_{workspace}")
        if group == "Pollution indices":
            choices = index_names
        else:
            choices = [name for name, (col, _) in parameters.items()
                       if group_for(name, col) == group]
        param_key = f"parameter_{workspace}_{group}"
        if choices and st.session_state.get(param_key) not in choices:
            st.session_state[param_key] = choices[0]
        selected = st.selectbox("Parameter", choices or ["No uploaded parameters in this group"],
                                disabled=not bool(choices), key=param_key)

        if group == "Pollution indices":
            if points is None:
                st.caption("Upload sampling data and run analysis to calculate WQI, HPI or WPI.")
            elif f"{workspace}:{selected}" not in all_index_results:
                st.info(f"{workspace} {selected} has not been calculated yet. Calculate it with {workspace} reference values.")
                if st.button(f"Calculate {workspace} {selected}", key=f"calculate_{workspace}_{selected}", use_container_width=True):
                    st.session_state[f"indices_method_{workspace}"] = selected
                    open_indices_panel(points, fingerprint, workspace)
            else:
                st.success(f"{workspace} {selected} is calculated and ready for mapping.")

        interpolation = st.segmented_control("Interpolation method", ["IDW", "Kriging"],
                                              default="IDW", key=f"reference_interpolation_{workspace}")
        # The map stays large: secondary controls are tucked into one drawer.
        with st.expander("Map layers & advanced settings", expanded=False):
            opacity = st.slider("Raster opacity", 0, 100, 70, step=5,
                                format="%d%%", key=f"raster_opacity_{workspace}")
            show_points = st.checkbox("Show sampling points", value=True, key=f"reference_show_points_{workspace}")
            show_boundary = st.checkbox("Show study boundary", value=True, key=f"reference_show_boundary_{workspace}")
            show_surface = st.checkbox("Show interpolated screening map", value=True,
                                      key=f"reference_show_surface_{workspace}")
            resolution = st.slider("Grid width (cells)", 50, 180, 100, step=10)
            power = st.slider("IDW power", 1.0, 4.0, 2.0, step=0.5)
        config_text = (f"{group} · {selected} · {interpolation} · {opacity}% opacity · "
                       f"Points {'visible' if show_points else 'hidden'} · "
                       f"Boundary {'visible' if show_boundary else 'hidden'} · "
                       f"Surface {'visible' if show_surface else 'hidden'}")
        st.caption(f"**Current configuration — {workspace}**")
        st.caption(config_text)
        if points is not None:
            if group != "Pollution indices" and st.button("🧪 WQI / HPI / WPI maps", key=f"open_index_dialog_{workspace}", use_container_width=True):
                open_indices_panel(points, fingerprint, workspace)
            if st.button("📊 Piper Plot", key="open_piper_dialog", use_container_width=True):
                open_piper_plot(points)
            if group == "Pollution indices" and active_index is not None and "__WaterIndexScore" in points:
                st.download_button("Download calculated indices CSV",
                                   active_index["table"].to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"{active_index['method'].lower()}_values.csv",
                                   mime="text/csv", use_container_width=True)
            with st.popover("Chart and data preview", use_container_width=True):
                st.dataframe(points.drop(columns="geometry"), width="stretch", height=180)
                st.download_button("Download merged CSV", points.drop(columns="geometry")
                                   .to_csv(index=False).encode("utf-8-sig"),
                                   file_name="merged_water_quality.csv", mime="text/csv")

# Resolve selected group's parameter to a numeric dataset field.
if group == "Pollution indices":
    selected_result = all_index_results.get(f"{workspace}:{selected}")
    if points is not None and selected_result is not None:
        points["__WaterIndexScore"] = pd.Series(selected_result["score"], index=points.index)
        active_index = selected_result
        parameters[selected] = ("__WaterIndexScore", "index")
    else:
        parameters.pop(selected, None)

field, unit = parameters.get(selected, (None, ""))
valid = None
if points is not None and field:
    points[field] = number_series(points[field])
    valid = points.dropna(subset=[field]).copy()

# Risk threshold configuration: use official references only for analytes for which
# a documented matching limit exists; otherwise require a manual study threshold.
risk_limit = None
risk_lower = None
risk_direction = "Above"
risk_source = None
moderate_fraction = 0.75
if field and valid is not None and not valid.empty:
    with right:
        with st.expander("Reference & screening rules", expanded=False):
            risk_preset = f"{workspace} drinking-water"
            st.caption(f"Parameter screening uses the {workspace} reference only. Unsupported analytes are not assigned invented standards.")
            if group == "Pollution indices":
                # BIS/WHO/EPA supply constituent limits but do not define these index score classes
                # the index score risk cutoffs used by this particular index method.
                st.caption("Index risk bands are METHOD-DEFINED screening bands, not WHO/BIS official risk categories.")
                index_cutoffs = {"WQI": (50.0, 100.0), "HPI": (75.0, 100.0), "WPI": (0.75, 1.0)}
                default_moderate, default_high = index_cutoffs[selected]
                risk_limit = st.number_input("High band begins above", min_value=0.000001, value=default_high,
                    key=f"index_high_{workspace}_{selected}")
                moderate_index_limit = st.number_input("Moderate band begins at", min_value=0.000001,
                    value=default_moderate, max_value=float(risk_limit), key=f"index_mid_{workspace}_{selected}")
                risk_source = f"{workspace} constituent limits; user-editable {selected} index bands"
                risk_direction = "Above"
            elif workspace == "WHO":
                if field in WHO_GUIDELINES and who_standard(field):
                    risk_limit = WHO_GUIDELINES[field][0]
                    risk_source = WHO_NAME
                else:
                    st.info("WHO numeric drinking-water limit unavailable for this parameter or requires analyte-species confirmation. No automatic risk map for this parameter.")
            elif workspace == "USEPA":
                # US EPA has numeric drinking-water standards for SELECTED analytes only.
                # BOD/COD/DO and many other water-quality measures do not have a universal
                # federal drinking-water MCL. Never invent an EPA value for these fields.
                lookup = epa_standard(field)
                has_epa_limit = lookup in EPA_LIMITS
                if has_epa_limit:
                    st.caption(epa_limit_note(field))
                else:
                    st.warning(
                        f"US EPA has no directly applicable numeric drinking-water "
                        f"limit configured for {selected}. BOD has no federal drinking-water "
                        "MCL; lead/copper use treatment-technique rules. "
                        "You can still perform a study-specific spatial screening "
                        "by providing a documented threshold below."
                    )
                choice = st.radio(
                    "Screening threshold source",
                    ["US EPA reference", "Custom study threshold"] if has_epa_limit
                    else ["Custom study threshold", "No screening (values only)"],
                    horizontal=False,
                    key=f"epa_threshold_mode_{group}_{field}",
                )
                if choice == "US EPA reference":
                    risk_limit, _ideal, risk_lower, detail, category = EPA_LIMITS[lookup]
                    risk_source = f"{EPA_NAME} ({category}: {detail})"
                    if category == "Secondary":
                        st.warning(
                            "EPA secondary guidelines are generally non-enforceable "
                            "aesthetic recommendations, not health-risk limits."
                        )
                elif choice == "Custom study threshold":
                    st.caption(
                        "Manual thresholds are NOT US EPA standards. Specify a scientifically "
                        "justified limit for the study's water body, units and intended use. "
                        "No classification is generated until you enter a valid threshold."
                    )
                    direction = st.selectbox(
                        "Exceedance rule", ["Above", "Below", "Outside range"],
                        key=f"epa_custom_direction_{field}",
                    )
                    upper_text = st.text_input(
                        "Upper limit / screening threshold" + (f" ({unit})" if unit else ""),
                        value="", placeholder="Enter your documented threshold",
                        key=f"epa_custom_upper_{field}",
                    ).strip()
                    lower_text = ""
                    if direction == "Outside range":
                        lower_text = st.text_input(
                            "Lower screening limit" + (f" ({unit})" if unit else ""),
                            value="", placeholder="Enter lower limit",
                            key=f"epa_custom_lower_{field}",
                        ).strip()
                    study_source = st.text_input(
                        "Study reference / source", placeholder="e.g. documented local water-quality criterion",
                        key=f"epa_custom_source_{field}",
                    ).strip()
                    if upper_text:
                        try:
                            import math
                            candidate = float(upper_text)
                            if not math.isfinite(candidate) or candidate <= 0:
                                raise ValueError("Enter a finite, positive threshold")
                            if direction == "Outside range":
                                lo = float(lower_text)
                                if not math.isfinite(lo) or lo >= candidate:
                                    raise ValueError("Lower limit must be below the upper limit")
                                risk_lower = lo
                            risk_limit = candidate
                            risk_direction = direction
                            risk_source = (
                                f"Custom study threshold ({study_source}) — NOT an EPA limit"
                                if study_source else "Custom study threshold (source not supplied) — NOT an EPA limit"
                            )
                            if not study_source:
                                st.warning("Add a reference/source before using the risk map for reporting.")
                        except ValueError:
                            st.error("Enter valid numeric limits in the units of your selected parameter.")
                            risk_limit = None
                            risk_source = None
                    else:
                        st.info("Enter a custom threshold to enable risk zones and predicted-site counts.")
                else:
                    st.info("EPA limit unavailable; showing interpolation values without classification.")
            else:
                lookup = field_to_standard(field)
                if lookup in BIS_ACCEPTABLE:
                    std, ideal, low, _ = BIS_ACCEPTABLE[lookup]
                    risk_limit, risk_lower = std, low
                    risk_source = PRESET_NAME
                else:
                    st.info("BIS acceptable limit unavailable for this parameter. No automatic risk map for this parameter.")
            if group != "Pollution indices" and field == "pH" and risk_limit is not None:
                risk_direction = "Outside range"
            if risk_limit is not None:
                if risk_direction == "Outside range":
                    st.caption(f"Screening outside {risk_lower:g}–{risk_limit:g} {unit}")
                else:
                    st.caption(f"Screening {risk_direction.lower()} {risk_limit:g} {unit}")
            if group == "Pollution indices":
                moderate_fraction = float(moderate_index_limit) / float(risk_limit)
            else:
                moderate_fraction = st.slider(
                "Moderate warning band starts at (% of upper limit)",
                min_value=50, max_value=95, value=75, step=5,
                help="Application-defined early warning only, NOT a WHO/BIS classification. "
                     "For Below thresholds the warning band extends to threshold / fraction; "
                     "for two-sided pH ranges it covers the outer (100-fraction)% of the permitted span on either side.",
                key=f"moderate_fraction_{workspace}_{group}_{selected}",
                ) / 100.0
            st.caption("Predictions are leave-one-out estimates *at existing sampling locations*, not newly discovered sites or verified health-risk predictions.")

if workspace == "USEPA" and field and valid is not None and not valid.empty and risk_limit is None and group != "Pollution indices":
    with right:
        st.info("US EPA: no applicable limit for this parameter. Open **Reference & screening rules** to enter a documented custom threshold, or view unclassified IDW/Kriging values.")

risk_table = None
risk_predicted_count = None
risk_observed_count = None
risk_predicted_available = 0
risk_failure = None
if valid is not None and not valid.empty and field and risk_limit is not None:
    try:
        risk_table, risk_predicted_count, risk_observed_count, risk_predicted_available = predict_site_risks(
            valid, field, interpolation, risk_limit, risk_direction, power,
            lower=risk_lower, upper=risk_limit)
    except Exception as exc:
        risk_failure = str(exc)

# Shared observed-site classes: these are NOT inferred from marker fill colours.
site_classes = None
site_class_counts = {}
if valid is not None and not valid.empty and risk_limit is not None:
    site_classes = pd.Series(
        classify(valid[field].to_numpy(), risk_limit, risk_direction, risk_lower, moderate_fraction),
        index=valid.index,
    )
    site_class_counts = site_classes.value_counts().to_dict()

# Risk category selection also controls map emphasis and the filtered site table.
with right:
    with st.container(border=True):
        st.markdown('<div class="aqua-control-head">◉ Site Risk Summary</div>', unsafe_allow_html=True)
        if site_classes is not None:
            rc = st.columns(3)
            for c, label, color in zip(rc, ["No risk flag", "Moderate", "High"], ["#22c55e", "#facc15", "#ef4444"]):
                c.markdown(f"<div style='border-top:4px solid {color};padding-top:4px;font-size:.78rem'><b>{site_class_counts.get(label,0)}</b><div>{label}</div></div>", unsafe_allow_html=True)
            chosen_risk = st.segmented_control("Highlight sites", ["All", "No risk flag", "Moderate", "High"],
                default="All", key=f"risk_category_filter_{workspace}_{group}_{selected}")
        else:
            chosen_risk = "All"
            st.caption("Risk classes need valid observations and an applicable screening limit.")
        if points is not None:
            total = len(points)
            available = len(valid) if valid is not None else 0
            missing = total - available
            st.caption(f"Data coverage: {available}/{total} valid selected observations · {missing} missing")
            if source_status == "Synthetic/test data":
                st.warning("SYNTHETIC / DEMONSTRATION · Not measured")
            elif source_status == "Unverified observations":
                st.info("UNVERIFIED · User-uploaded observations")
            else:
                st.info("USER-VERIFIED · Not independently audited")

filtered_site_indices = list(site_classes[site_classes == chosen_risk].index) if site_classes is not None and chosen_risk != "All" else None
with kpi_row.container():
    stat_cols = st.columns(4, gap="small")
    stat_cols[0].metric("Sampling sites", str(len(points)) if points is not None else "—")
    stat_cols[1].metric("Predicted flagged sites", str(risk_predicted_count) if risk_predicted_count is not None else "—", help="Leave-one-out model predictions at existing sites; distinct from observed exceedances")
    stat_cols[2].metric("Observed exceedances", str(risk_observed_count) if risk_observed_count is not None else "—")
    stat_cols[3].metric("Mean selected", f"{valid[field].mean():.3f} {unit}" if valid is not None and not valid.empty else "—")
with left:
    if risk_failure:
        st.caption("Risk-site prediction unavailable: " + risk_failure)
    if risk_table is not None:
        with st.popover("Risk sites and prediction table"):
            st.caption(f"{risk_predicted_available} leave-one-out predictions · {risk_source}. Predicted flags are model-screening outputs, not new sampled locations.")
            display_risk = risk_table.copy()
            if site_classes is not None:
                display_risk["Observed_Screening_Class"] = site_classes.reindex(display_risk.index).fillna("Unavailable")
            if filtered_site_indices is not None:
                display_risk = display_risk.loc[display_risk.index.intersection(filtered_site_indices)]
            st.dataframe(display_risk, width="stretch", height=280)
            st.download_button("Download selected site results", display_risk.to_csv(index=False).encode("utf-8-sig"), file_name="filtered_screening_sites.csv", mime="text/csv")
    if site_classes is not None:
        with st.popover("🔎 Site classification · filter & export"):
            observed = valid[[c for c in ["Site_ID", "Site_Name", field, "Source_File"] if c in valid.columns]].copy()
            observed["Observed_Screening_Class"] = site_classes.reindex(observed.index)
            if filtered_site_indices is not None:
                observed = observed.loc[observed.index.intersection(filtered_site_indices)]
            st.caption(f"{len(observed)} sites match '{chosen_risk}'. These are observed-site classifications, not new predicted sites.")
            st.dataframe(observed, width="stretch", height=230)
            st.download_button("Download site classification CSV", observed.to_csv(index=False).encode('utf-8-sig'),
                file_name=f"{workspace}_{selected}_observed_screening.csv", mime="text/csv")
    st.markdown('<div class="aqua-section"><span>▧ Water Quality Map · Interpolation &amp; Risk Screening</span><span style="font-size:.68rem;font-weight:500">SATELLITE · GIS</span></div>', unsafe_allow_html=True)
    if error_message:
        st.error(error_message)
    elif not boundary_uploads or not csv_uploads:
        pass
    elif not running:
        pass
    overlay, overlay_bounds, predicted_range = None, None, None
    risk_zone_image, risk_zone_area = None, None
    if points is not None and field and valid is not None and not valid.empty and show_surface:
        try:
            with st.spinner(f"Rendering {interpolation} surface..."):
                overlay, overlay_bounds, predicted_range, risk_zone_image, risk_zone_area = create_surface(
                    boundary, valid, field, interpolation, resolution, power,
                    risk_threshold=risk_limit if risk_source else None,
                    risk_direction=risk_direction, risk_lower=risk_lower,
                    return_risk=True, moderate_fraction=moderate_fraction)
        except Exception as exc:
            st.warning(f"{interpolation} interpolation unavailable: {exc}")
    if boundary is not None and valid is not None and not valid.empty:
        with st.popover("📄 Study report · PDF / map PNG"):
            st.caption("Includes a GIS thematic screening map, references, sites, threshold and method. Satellite imagery is exported separately using the MapLibre download icon.")
            report_notes = [
                "Three screening bands are application-defined, not official BIS/WHO/US EPA categories.",
                "Spatial estimates are modelled and should be validated with independent observations.",
                f"Data status: {source_status}. Source status is declared by the uploader.",
                "Unreported or unmatched regulatory limits must not be interpreted as zero risk.",
            ]
            if st.button("Prepare study report", key=f"prepare_report_{workspace}_{group}_{selected}_{interpolation}"):
                try:
                    pdf_bytes, map_png = make_report_pdf(
                        workspace=workspace, parameter=selected, method=interpolation,
                        field=field, unit=unit, boundary=boundary, samples=valid,
                        reference=risk_source or "Not available", threshold=risk_limit,
                        lower=risk_lower, moderate_fraction=moderate_fraction,
                        data_status=source_status,
                        classes=site_classes.reindex(valid.index).to_list() if site_classes is not None else None,
                        risk_table=risk_table, risk_area=risk_zone_area,
                        risk_image=risk_zone_image, risk_bounds=overlay_bounds,
                        interpolated_range=predicted_range, quality_notes=report_notes,
                    )
                    st.session_state["prepared_report"] = (pdf_bytes, map_png, fingerprint, workspace, selected, interpolation)
                except Exception as exc:
                    st.error(f"Report generation failed: {exc}")
            prepared = st.session_state.get("prepared_report")
            if prepared and prepared[2:] == (fingerprint, workspace, selected, interpolation):
                st.download_button("Download PDF report", prepared[0], file_name=f"water_quality_{workspace}_{selected}_{interpolation}.pdf", mime="application/pdf")
                st.download_button("Download thematic map PNG", prepared[1], file_name=f"water_quality_{workspace}_{selected}_{interpolation}.png", mime="image/png")
        try:
            show_maplibre(boundary=boundary, samples=points, metal_column=field,
                site_column="Site_Name", height=650, overlay_image=overlay,
                overlay_bounds=overlay_bounds, value_unit=unit,
                raster_opacity=opacity / 100.0, show_points=show_points,
                show_boundary=show_boundary,
                point_color=GROUP_POINT_COLORS[group],
                default_basemap="Satellite (Esri World Imagery)",
                parameter_label=selected, parameter_group=group,
                interpolation_method=interpolation if overlay is not None else None,
                interpolation_range=predicted_range if overlay is not None else None,
                risk_threshold=risk_limit if risk_source else None,
                risk_threshold_direction=risk_direction,
                risk_reference=risk_source,
                risk_zone_image=risk_zone_image,
                risk_zone_area_km2=risk_zone_area,
                moderate_fraction=moderate_fraction,
                risk_site_indices=(risk_table.index[risk_table["Predicted_Exceeds_Threshold"]].tolist() if risk_table is not None else []),
                risk_lower=risk_lower, highlighted_indices=filtered_site_indices)
        except Exception as map_exc:
            st.error(f"MapLibre data preparation failed: {map_exc}")
            st.info("Check shapefile CRS, uploaded coordinate mapping, and the MapLibre HTML file.")
    else:
        show_empty_map(height=650)

# Compact physical parameter summary, only from actual uploaded values.
if points is not None:
    with st.sidebar.expander("Physical parameter means", expanded=False):
        for col, (label, suffix) in PHYSICAL.items():
            if col in points:
                s = number_series(points[col]).dropna()
                if not s.empty:
                    st.caption(f"{label}: {s.mean():.2f} {suffix}")
