"""Piper diagram from uploaded hydrochemistry CSV data (mg/L)."""
import io
import math
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

EQUIVALENT_WEIGHTS = {
    'Ca': 40.078 / 2, 'Mg': 24.305 / 2, 'Na': 22.98977,
    'K': 39.0983, 'HCO3': 61.0168, 'CO3': 60.0089 / 2,
    'Cl': 35.453, 'SO4': 96.06 / 2,
}
REQUIRED = ('Ca', 'Mg', 'Na', 'HCO3', 'Cl', 'SO4')
OPTIONAL = ('K', 'CO3')
ALIASES = {
    'Ca': ('ca','calcium','camgl','calciummgl'),
    'Mg': ('mg','magnesium','mgmgl','magnesiummgl'),
    'Na': ('na','sodium','namgl','sodiummgl'),
    'K': ('k','potassium','kmgl','potassiummgl'),
    'HCO3': ('hco3','bicarbonate','bicarbonatemgl','hco3mgl','hydrogencarbonate'),
    'CO3': ('co3','carbonate','carbonatemgl','co3mgl'),
    'Cl': ('cl','chloride','chloridemgl','clmgl'),
    'SO4': ('so4','sulphate','sulfate','so4mgl','sulphatemgl','sulfatemgl'),
}

def _norm(name):
    return re.sub(r'[^a-z0-9]+', '', str(name).lower())

def suggest_column(columns, ion):
    choices = {_norm(col): col for col in columns}
    for alias in ALIASES[ion]:
        if alias in choices:
            return choices[alias]
    return None

def _mg_l_numeric(series):
    # Numeric mg/L only; do not reinterpret detection-limit symbols or other units.
    return pd.to_numeric(series.astype('string').str.strip(), errors='coerce')

def prepare_piper_data(df, mapping, assume_missing_optional_zero=False):
    """Return plot-ready hydrochemical fractions + QA table.

    mapping: dict from ion codes to column names, or None for optional ions.
    Strictly requires mg/L ion observations, not meq/L or general TDS.
    """
    missing = [ion for ion in REQUIRED if not mapping.get(ion)]
    if missing:
        raise ValueError('Required ion columns not mapped: ' + ', '.join(missing))
    absent_optional = [ion for ion in OPTIONAL if not mapping.get(ion)]
    if absent_optional and not assume_missing_optional_zero:
        raise ValueError('Map optional ions or explicitly select the zero-assumption option: ' + ', '.join(absent_optional))

    out = pd.DataFrame(index=df.index)
    out['Site'] = df['Site_Name'].astype('string').fillna('Unknown') if 'Site_Name' in df else (
        df['Site_ID'].astype('string').fillna('Unknown') if 'Site_ID' in df else pd.Series([f'Site {i+1}' for i in range(len(df))], index=df.index)
    )
    for ion in EQUIVALENT_WEIGHTS:
        if mapping.get(ion):
            vals = _mg_l_numeric(df[mapping[ion]])
        else:
            vals = pd.Series(0.0, index=df.index)
        out[f'{ion}_mg_L'] = vals
        out[f'{ion}_meq_L'] = vals / EQUIVALENT_WEIGHTS[ion]

    cols = [f'{ion}_mg_L' for ion in EQUIVALENT_WEIGHTS]
    invalid = out[cols].isna().any(axis=1) | out[cols].lt(0).any(axis=1)
    invalid |= (out[[f'{ion}_meq_L' for ion in ('Ca','Mg','Na','K')]].sum(axis=1) <= 0)
    invalid |= (out[[f'{ion}_meq_L' for ion in ('HCO3','CO3','Cl','SO4')]].sum(axis=1) <= 0)
    clean = out.loc[~invalid].copy()
    if clean.empty:
        raise ValueError('No sites with complete, non-negative ion values and positive ionic totals.')
    cat_total = sum(clean[f'{ion}_meq_L'] for ion in ('Ca','Mg','Na','K'))
    an_total = sum(clean[f'{ion}_meq_L'] for ion in ('HCO3','CO3','Cl','SO4'))
    clean['Charge_Balance_Error_pct'] = 100*(cat_total-an_total)/(cat_total+an_total)
    clean['Ca_pct'] = 100*clean['Ca_meq_L']/cat_total
    clean['Mg_pct'] = 100*clean['Mg_meq_L']/cat_total
    clean['NaK_pct'] = 100*(clean['Na_meq_L']+clean['K_meq_L'])/cat_total
    clean['HCO3CO3_pct'] = 100*(clean['HCO3_meq_L']+clean['CO3_meq_L'])/an_total
    clean['SO4_pct'] = 100*clean['SO4_meq_L']/an_total
    clean['Cl_pct'] = 100*clean['Cl_meq_L']/an_total
    def facies(row):
        c = {'Ca':row.Ca_pct, 'Mg':row.Mg_pct, 'Na+K':row.NaK_pct}
        a = {'HCO3+CO3':row.HCO3CO3_pct, 'SO4':row.SO4_pct, 'Cl':row.Cl_pct}
        cat = max(c, key=c.get) if max(c.values()) >= 50 else 'Mixed cations'
        an = max(a, key=a.get) if max(a.values()) >= 50 else 'Mixed anions'
        return f'{cat} – {an}'
    clean['Hydrochemical_Facies'] = clean.apply(facies, axis=1)
    clean['Charge_Balance_Flag'] = np.where(clean.Charge_Balance_Error_pct.abs() > 10, 'Review (>10%)', 'Within ±10% screening')
    return clean.reset_index(drop=True), int(invalid.sum())


def piper_figure(data):
    """Create Piper triangles and central diamond in Cartesian coordinates."""
    h = math.sqrt(3)/2
    gap = 0.34
    right_offset = 1 + gap
    center = (1 + right_offset)/2
    diamond_bottom = h + 0.16
    diamond_width = 0.95
    diamond_height = math.sqrt(3) * diamond_width

    fig = go.Figure()
    def outline(vertices):
        pts = vertices + [vertices[0]]
        fig.add_trace(go.Scatter(x=[p[0] for p in pts],y=[p[1] for p in pts],mode='lines',
                                 line=dict(color='#475569',width=1.6),hoverinfo='skip',showlegend=False))
    outline([(0,0),(1,0),(.5,h)])
    outline([(right_offset,0),(right_offset+1,0),(right_offset+.5,h)])
    outline([(center,diamond_bottom),(center-diamond_width/2,diamond_bottom+diamond_height/2),
             (center,diamond_bottom+diamond_height),(center+diamond_width/2,diamond_bottom+diamond_height/2)])

    # 20% interval grids, drawn using triangle barycentric geometry.
    def grids(offset):
        for i in range(1,5):
            f = i/5
            for a,b in [((f,0),(f/2,h*(1-f))),
                        ((1-f,0),(1-f/2,h*f)),
                        ((f/2,h*f),(1-f/2,h*f))]:
                fig.add_trace(go.Scatter(x=[a[0]+offset,b[0]+offset],y=[a[1],b[1]],mode='lines',
                                         line=dict(color='#e2e8f0',width=.7),hoverinfo='skip',showlegend=False))
    grids(0); grids(right_offset)

    ca = data.Ca_pct / 100; mg = data.Mg_pct / 100; nak = data.NaK_pct / 100
    bicarb = data.HCO3CO3_pct / 100; so4 = data.SO4_pct / 100; cl = data.Cl_pct / 100
    cat_x = nak + .5*mg
    cat_y = h*mg
    an_x = right_offset + cl + .5*so4
    an_y = h*so4
    strong_anions = cl + so4
    dia_x = center + (diamond_width/2)*(strong_anions - nak)
    dia_y = diamond_bottom + (diamond_height/2)*(strong_anions + nak)

    hover = [f'<b>{r.Site}</b><br>Facies: {r.Hydrochemical_Facies}<br>Charge balance error: {r.Charge_Balance_Error_pct:.1f}%'
             for r in data.itertuples(index=False)]
    for label, xs, ys, color in [
        ('Cations',cat_x,cat_y,'#2563eb'),
        ('Anions',an_x,an_y,'#059669'),
        ('Piper diamond',dia_x,dia_y,'#db2777'),
    ]:
        fig.add_trace(go.Scatter(x=xs,y=ys,mode='markers',name=label,
                       marker=dict(size=9,color=color,opacity=.85,line=dict(width=1,color='white')),
                       text=hover,hovertemplate='%{text}<extra></extra>'))
    annotations = [
        ('Ca²⁺',-.02,-.10),('Na⁺ + K⁺',1.04,-.10),('Mg²⁺',.5,h+.11),
        ('HCO₃⁻ + CO₃²⁻',right_offset-.08,-.10),('Cl⁻',right_offset+1.02,-.10),
        ('SO₄²⁻',right_offset+.5,h+.11),('Hydrochemical facies',center,diamond_bottom+diamond_height+.17),
    ]
    for text,x,y in annotations:
        fig.add_annotation(x=x,y=y,text=text,showarrow=False,font=dict(size=11,color='#334155'))
    fig.update_xaxes(visible=False,range=[-.25,right_offset+1.25],scaleanchor='y',scaleratio=1)
    fig.update_yaxes(visible=False,range=[-.25,diamond_bottom+diamond_height+.40])
    fig.update_layout(height=680,margin=dict(l=15,r=15,t=25,b=10),
                      plot_bgcolor='white',legend=dict(orientation='h',y=-.02,x=.5,xanchor='center'))
    return fig


def render_piper_panel(samples):
    """Render mapping, calculations, figure and downloadable facies table."""
    st.subheader('Piper Diagram — Hydrochemical Facies')
    st.caption('Major ions must be in mg/L. Piper percentages are calculated from milliequivalents per litre (meq/L), not raw mg/L.')
    columns = list(samples.columns)
    options = ['— Not provided —'] + columns
    mapping = {}
    with st.expander('Major-ion column mapping', expanded=True):
        st.info('Required: Ca, Mg, Na, HCO₃, Cl, SO₄. K and CO₃ may be treated as zero only if you explicitly confirm that assumption.')
        grid = st.columns(4)
        for i, ion in enumerate(EQUIVALENT_WEIGHTS):
            guess = suggest_column(columns,ion)
            choice = grid[i % 4].selectbox(f'{ion} (mg/L)', options,
                       index=options.index(guess) if guess else 0,key=f'piper_ion_{ion}')
            mapping[ion] = None if choice == options[0] else choice
        zeros = st.checkbox('For this analysis, assume omitted K and/or CO₃ are zero (disclose in report)',value=False)
        st.caption('For charge-balance quality assurance, a value within ±10% is shown as a screening flag, not laboratory certification.')
    if not st.button('Generate Piper Plot',type='primary',key='generate_piper'):
        return
    try:
        result, dropped = prepare_piper_data(samples,mapping,zeros)
    except ValueError as e:
        st.error(str(e)); return
    st.success(f'Plotted {len(result)} locations; excluded {dropped} rows with invalid or missing required major-ion results.')
    if (result.Charge_Balance_Error_pct.abs() > 10).any():
        st.warning('Some samples exceed ±10% charge-balance error. Review ionic analyses and units before interpretation.')
    st.plotly_chart(piper_figure(result),width="stretch")
    columns_to_show = ['Site','Ca_pct','Mg_pct','NaK_pct','HCO3CO3_pct','SO4_pct','Cl_pct',
                       'Charge_Balance_Error_pct','Charge_Balance_Flag','Hydrochemical_Facies']
    st.dataframe(result[columns_to_show],width="stretch")
    st.download_button('Download Piper facies table (CSV)',data=result[columns_to_show].to_csv(index=False).encode('utf-8-sig'),
                       file_name='piper_facies_results.csv',mime='text/csv')
