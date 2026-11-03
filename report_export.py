"""Generate a study report with a server-rendered thematic risk map.

Satellite basemap imagery is NOT reproduced here. The separate browser MapLibre
PNG button exports the visible satellite map when browser/provider permissions allow.
"""
import base64
import io
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

RISK_COLORS = {'No risk flag': '#22c55e', 'Moderate': '#facc15', 'High': '#ef4444', 'Unavailable': '#94a3b8'}


def thematic_map_png(boundary, points, field, unit, title, risk_image=None, image_bounds=None,
                     class_labels=None):
    fig, ax = plt.subplots(figsize=(10.5, 6.1), dpi=145)
    ax.set_facecolor('#e8f7fb')
    if risk_image and image_bounds:
        raw = base64.b64decode(risk_image.split(',', 1)[-1])
        raster = Image.open(io.BytesIO(raw))
        ax.imshow(raster, extent=image_bounds, origin='upper', interpolation='nearest', zorder=1)
    boundary.to_crs('EPSG:4326').boundary.plot(ax=ax, color='#087eac', linewidth=1.3, zorder=2)
    pts = points.to_crs('EPSG:4326')
    x = pts.geometry.x.to_numpy()
    y = pts.geometry.y.to_numpy()
    if class_labels is not None:
        fill = [RISK_COLORS.get(str(v), '#94a3b8') for v in class_labels]
    else:
        fill = '#087eac'
    ax.scatter(x, y, c=fill, s=34, edgecolor='white', linewidth=0.8, zorder=3)
    xmin, ymin, xmax, ymax = boundary.to_crs('EPSG:4326').total_bounds
    dx = max(.02, (xmax-xmin)*.03)
    dy = max(.02, (ymax-ymin)*.03)
    ax.set_xlim(xmin-dx, xmax+dx)
    ax.set_ylim(ymin-dy, ymax+dy)
    ax.set_xlabel('Longitude (degrees east)')
    ax.set_ylabel('Latitude (degrees north)')
    ax.set_title(title, color='#073b5d', fontweight='bold', fontsize=13)
    ax.set_aspect('equal', adjustable='box')
    ax.grid(alpha=.15)
    ax.legend(handles=[Patch(color='#22c55e',label='Not flagged'),Patch(color='#facc15',label='Moderate'),
                       Patch(color='#ef4444',label='High')], loc='lower right', fontsize=8)
    fig.text(.05, .012, 'Estimated screening only. No satellite image included. Colours are application-defined.', fontsize=8, color='#475569')
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=145, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return buf.getvalue()


def make_report_pdf(*, workspace, parameter, method, field, unit, boundary, samples,
                    reference, threshold, lower, moderate_fraction, data_status,
                    classes, risk_table, risk_area, risk_image, risk_bounds,
                    interpolated_range, quality_notes):
    map_png = thematic_map_png(boundary, samples, field, unit,
        f'{parameter} | {workspace} | {method} screening', risk_image, risk_bounds, classes)
    buf = io.BytesIO()
    page_w, page_h = landscape(A4)
    pdf = canvas.Canvas(buf, pagesize=(page_w, page_h))
    navy = colors.HexColor('#073b5d')
    blue = colors.HexColor('#087eac')
    def header(page_no):
        pdf.setFillColor(navy); pdf.rect(0,page_h-64,page_w,64,fill=1,stroke=0)
        pdf.setFillColor(colors.white); pdf.setFont('Helvetica-Bold',20)
        pdf.drawString(34,page_h-35,'WATER QUALITY | SPATIAL SCREENING REPORT')
        pdf.setFont('Helvetica',9)
        pdf.drawRightString(page_w-28,page_h-34,f'Page {page_no} | {datetime.now(timezone.utc).strftime("%Y-%m-%d UTC")}')
    def line(y, s, bold=False, size=10):
        pdf.setFont('Helvetica-Bold' if bold else 'Helvetica',size)
        pdf.setFillColor(navy if bold else colors.HexColor('#334155'))
        pdf.drawString(34,y,str(s)[:135])
    header(1)
    line(page_h-84,f'Standard: {workspace} | Parameter: {parameter} | Interpolation: {method}',True,12)
    line(page_h-102,f'Dataset status (user-declared): {data_status} | Sites: {len(samples)}')
    if threshold is not None:
        lim = f'{float(threshold):g} {unit}'
        if lower is not None: lim = f'{float(lower):g} to {lim}'
        line(page_h-120,f'Reference: {str(reference)[:90]} | Screening limit: {lim}',size=9)
    else:
        line(page_h-120,'No matching reference limit: risk classes not available.',size=9)
    pdf.drawImage(ImageReader(io.BytesIO(map_png)), 35, 65, width=530, height=330, preserveAspectRatio=True, anchor='c')
    x=580
    def info(label,value,y):
        pdf.setFont('Helvetica-Bold',10); pdf.setFillColor(blue); pdf.drawString(x,y,label)
        pdf.setFont('Helvetica',10); pdf.setFillColor(navy); pdf.drawString(x,y-16,str(value)[:38])
    cls=list(classes) if classes is not None else []
    info('Observed no flag',sum(v=='No risk flag' for v in cls),page_h-155)
    info('Observed moderate',sum(v=='Moderate' for v in cls),page_h-198)
    info('Observed high',sum(v=='High' for v in cls),page_h-241)
    if risk_area:
        info('Modelled high area (approx.)',f'{risk_area.get("high",0):.2f} km2',page_h-284)
    if interpolated_range:
        info('Interpolated range',f'{interpolated_range[0]:.4g} - {interpolated_range[1]:.4g} {unit}',page_h-327)
    pdf.setFont('Helvetica',8); pdf.setFillColor(colors.HexColor('#64748b'))
    pdf.drawString(35,39,'Modelled raster risk does not establish drinking-water safety. Actual satellite map export is separate.')
    pdf.showPage(); header(2)
    line(page_h-88,'SAMPLING-SITE RESULTS',True,13)
    y=page_h-116
    headers=['Site','Observed','Class','LOO predicted','LOO flagged']
    xs=[35,240,340,450,610]
    for xx,h in zip(xs,headers):
        pdf.setFillColor(blue);pdf.setFont('Helvetica-Bold',9);pdf.drawString(xx,y,h)
    y-=18
    pred_col=next((c for c in getattr(risk_table,'columns',[]) if c.endswith('_LOO_Prediction')),None)
    for i, (idx,row) in enumerate(samples.iterrows()):
        if y < 82:
            pdf.showPage();header(3);y=page_h-92
        pdf.setFillColor(colors.HexColor('#334155'));pdf.setFont('Helvetica',8)
        site=str(row.get('Site_Name',row.get('Site_ID',idx)))[:30]
        value=row.get(field)
        predicted = risk_table.loc[idx,pred_col] if risk_table is not None and pred_col and idx in risk_table.index else None
        flag = risk_table.loc[idx,'Predicted_Exceeds_Threshold'] if risk_table is not None and idx in risk_table.index else None
        vals=[site,f'{float(value):.4g}' if value is not None else '—', str(cls[i]) if i<len(cls) else 'Unavailable',
              f'{float(predicted):.4g}' if predicted is not None and str(predicted)!='nan' else '—',
              'Yes' if flag is True or str(flag)=='True' else 'No / unavailable']
        for xx,txt in zip(xs,vals):pdf.drawString(xx,y,txt[:28])
        y-=15
    y-=16
    for note in quality_notes[:6]:
        if y<50:pdf.showPage();header(4);y=page_h-100
        line(y,str(note),size=8);y-=13
    pdf.showPage()
    pdf.save()
    return buf.getvalue(), map_png
