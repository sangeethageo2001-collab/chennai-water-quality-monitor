from pathlib import Path
import geopandas as gpd
import pandas as pd
import plotly.express as px
import streamlit as st
from maplibre_streamlit import show_maplibre
from interpolation import create_surface

st.set_page_config(page_title='Chennai Water Quality Monitor',layout='wide')
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'Data'
METALS={'Lead (Pb)':'Pb_mg_L','Cadmium (Cd)':'Cd_mg_L','Chromium (Cr)':'Cr_mg_L','Arsenic (As)':'As_mg_L','Mercury (Hg)':'Hg_mg_L','Nickel (Ni)':'Ni_mg_L','Copper (Cu)':'Cu_mg_L','Zinc (Zn)':'Zn_mg_L','Iron (Fe)':'Fe_mg_L','Manganese (Mn)':'Mn_mg_L'}

@st.cache_data
def load_data():
    boundary=gpd.read_file(DATA/'Chennai_new.shp')
    points=gpd.read_file(DATA/'Point_Data.shp')
    if boundary.crs is None or points.crs is None:
        raise ValueError('Your GIS layers need a correct source coordinate reference system (CRS).')
    return boundary.to_crs('EPSG:4326'),points.to_crs('EPSG:4326')

try:
    boundary,points=load_data()
except Exception as exc:
    st.error(f'Unable to load GIS layers: {exc}'); st.stop()

# Optional real temperature data: CSV keyed by Site_ID with Temperature_C column.
# Existing temperature shapefile fields are also detected (DBF field name may truncate).
temp_columns=['Temperature_C','Temp_C','Water_Temp','WTemp_C','TEMP_C','Temp']
existing_temp=next((col for col in temp_columns if col in points.columns),None)
if existing_temp is None:
    temp_file=DATA/'temperature_readings.csv'
    if temp_file.exists():
        try:
            readings=pd.read_csv(temp_file)
            if not {'Site_ID','Temperature_C'}.issubset(readings.columns):
                st.warning('temperature_readings.csv needs Site_ID and Temperature_C columns.')
            elif 'Site_ID' not in points.columns:
                st.warning('Cannot join temperature readings: sampling points lack Site_ID.')
            else:
                readings['Site_ID']=readings['Site_ID'].astype(str).str.strip()
                readings['Temperature_C']=pd.to_numeric(readings['Temperature_C'], errors='coerce')
                if readings['Site_ID'].duplicated().any():
                    st.warning('Duplicate Site_ID entries in temperature_readings.csv; fix before temperature mapping.')
                else:
                    points['Temperature_C']=points['Site_ID'].astype(str).str.strip().map(readings.set_index('Site_ID')['Temperature_C'])
                    existing_temp='Temperature_C'
        except Exception as exc:
            st.warning(f'Temperature CSV could not be loaded: {exc}')

st.title('Chennai Water Quality Monitor')
st.caption('MapLibre | Sampling observations and exploratory IDW / Kriging surfaces')
st.warning('SYNTHETIC_NOT_MEASURED: existing heavy-metal values are development test data. Interpolated surfaces are not measured pollution or water-safety assessments.')
options={k:(v,'mg/L') for k,v in METALS.items() if v in points.columns}
if existing_temp:
    options['Water Temperature (°C)']=(existing_temp,'°C')
if not options:
    st.error('No supported parameter columns found in Point_Data.shp.');st.stop()
selected=st.selectbox('Parameter',list(options))
field,unit=options[selected]
points=points.copy()
points[field]=pd.to_numeric(points[field],errors='coerce')
df=points.loc[points.geometry.notna() & (~points.geometry.is_empty)].copy()
valid=df.dropna(subset=[field]).copy()
if valid.empty:
    st.error('No numeric values for this parameter.');st.stop()

c1,c2,c3=st.columns(3)
c1.metric('Sampling locations',len(points))
c2.metric('Valid observations',len(valid))
c3.metric('Mean '+selected,f'{valid[field].mean():.3f} {unit}')

st.subheader('Interactive GIS map')
a,b,c=st.columns([1.2,1,1])
mode=a.selectbox('Surface visualization',['Sampling points only','IDW','Kriging'])
resolution=b.slider('Grid width (cells)',50,180,100,step=10,disabled=(mode=='Sampling points only'))
power=c.slider('IDW power',1.0,4.0,2.0,step=0.5,disabled=(mode!='IDW'))
overlay=None; overlay_bounds=None
if mode!='Sampling points only':
    if len(valid)<5:
        st.warning('Sparse data: spatial interpolation may be unreliable with fewer than 5 values.')
    try:
        with st.spinner('Calculating exploratory surface...'):
            overlay,overlay_bounds,value_range=create_surface(boundary,valid,field,mode,resolution,power)
        st.info(f'{mode} surface: observed value range {value_range[0]:.4g}–{value_range[1]:.4g} {unit}. Colours indicate relative concentration/temperature, not risk levels.')
    except Exception as exc:
        st.error(f'{mode} surface unavailable: {exc}')

show_maplibre(boundary=boundary,samples=df,metal_column=field,
    site_column='Site_Name' if 'Site_Name' in df else None,height=650,
    overlay_image=overlay,overlay_bounds=overlay_bounds,value_unit=unit)
st.caption('Satellite and 3D modes require internet access. The surface is a spatial estimate clipped to the study boundary. Do not interpret it as measured values across all land/water.')

st.subheader('Values by sampling site')
plot_df=valid.copy()
if 'Site_ID' not in plot_df:
    plot_df['Site_ID']=[f'Site {i}' for i in range(1,len(plot_df)+1)]
fig=px.bar(plot_df,x='Site_ID',y=field,hover_name='Site_Name' if 'Site_Name' in plot_df else None,
           labels={'Site_ID':'Sampling site',field:f'{selected} ({unit})'})
st.plotly_chart(fig,width='stretch')
st.subheader('Sample data')
st.dataframe(valid.drop(columns='geometry'),width='stretch')

if existing_temp is None:
    st.info('Temperature is not available in the uploaded sample schema. To add actual readings, create Data/temperature_readings.csv with Site_ID,Temperature_C. No temperature values are generated automatically.')
