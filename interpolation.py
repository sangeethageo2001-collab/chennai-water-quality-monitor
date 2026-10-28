"""Exploratory IDW / ordinary Kriging surfaces (EPSG:32644 projected metres)."""
from io import BytesIO
from base64 import b64encode
import numpy as np
from PIL import Image
import geopandas as gpd
from shapely.geometry import Point
from shapely.prepared import prep


def create_surface(boundary, samples, column, method="IDW", resolution=100, power=2.0):
    # Project before calculating distances: longitude/latitude degrees are not metres.
    projected = samples.dropna(subset=[column, "geometry"]).to_crs('EPSG:32644')
    projected = projected[(~projected.geometry.is_empty) & (projected.geometry.geom_type == 'Point')].copy()
    xy = np.array([(g.x, g.y) for g in projected.geometry], dtype=float)
    values = projected[column].to_numpy(dtype=float)
    good = np.isfinite(values) & np.all(np.isfinite(xy), axis=1)
    xy, values = xy[good], values[good]
    if len(xy) < 3:
        raise ValueError('At least 3 valid sample points are required.')
    if np.unique(xy, axis=0).shape[0] != len(xy):
        raise ValueError('Duplicate sampling coordinates detected. Resolve or aggregate replicates before interpolation.')
    region = boundary.to_crs('EPSG:32644').geometry.union_all()
    xmin,ymin,xmax,ymax = region.bounds
    nx = int(resolution)
    ny = max(2, round(nx*(ymax-ymin)/(xmax-xmin)))
    ny = min(ny, 250)
    xs = np.linspace(xmin, xmax, nx)
    ys = np.linspace(ymin, ymax, ny)
    xx, yy = np.meshgrid(xs,ys)
    if method == 'IDW':
        d2 = (xx[:,:,None]-xy[:,0])**2+(yy[:,:,None]-xy[:,1])**2
        zeros = d2 < 1e-10
        w = 1.0/np.maximum(d2, 1e-10)**(power/2)
        surface = (w @ values) / w.sum(axis=2)
        if zeros.any():
            for yy_idx, xx_idx in np.argwhere(zeros.any(axis=2)):
                surface[yy_idx,xx_idx] = values[np.flatnonzero(zeros[yy_idx,xx_idx])[0]]
    elif method == 'Kriging':
        try:
            from pykrige.ok import OrdinaryKriging
        except ImportError as e:
            raise RuntimeError('Kriging requires PyKrige. Run: pip install pykrige') from e
        if len(values) < 5:
            raise ValueError('Kriging needs at least 5 distinct points for this prototype.')
        model=OrdinaryKriging(xy[:,0],xy[:,1],values,variogram_model='spherical',verbose=False,enable_plotting=False)
        surface,_ = model.execute('grid',xs,ys)
        surface = np.asarray(surface.filled(np.nan) if hasattr(surface,'filled') else surface)
    else:
        raise ValueError('Unknown interpolation method')
    region_prep = prep(region)
    mask = np.fromiter((region_prep.covers(Point(float(x),float(y))) for x,y in zip(xx.ravel(),yy.ravel())), dtype=bool, count=xx.size).reshape(xx.shape)
    finite = surface[np.isfinite(surface) & mask]
    if finite.size == 0:
        raise ValueError('No interpolated grid cells inside boundary.')
    lo, hi = float(values.min()),float(values.max())
    span=max(hi-lo,1e-12)
    t=np.clip((surface-lo)/span,0,1)
    # green -> yellow -> red (relative to observed data range)
    rgb=np.empty((*t.shape,4),dtype=np.uint8)
    rgb[:,:,0]=np.where(t<.5, 40+420*t, 250).astype('uint8')
    rgb[:,:,1]=np.where(t<.5, 145+190*t, 240-420*(t-.5)).clip(0,255).astype('uint8')
    rgb[:,:,2]=np.where(t<.5, 75-120*t, 10).clip(0,255).astype('uint8')
    rgb[:,:,3]=np.where(mask & np.isfinite(surface), 190, 0).astype('uint8')
    im=Image.fromarray(np.flipud(rgb),'RGBA')
    buf=BytesIO(); im.save(buf,format='PNG')
    # geographic bounding rectangle for MapLibre image overlay
    corners=gpd.GeoSeries([Point(xmin,ymin),Point(xmax,ymax)],crs='EPSG:32644').to_crs('EPSG:4326')
    lons=[g.x for g in corners]; lats=[g.y for g in corners]
    return 'data:image/png;base64,'+b64encode(buf.getvalue()).decode(),[min(lons),min(lats),max(lons),max(lats)],(lo,hi)
