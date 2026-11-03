"""Exploratory leave-one-out predictions at observed sample locations.

These are *not* independent/new sites. Every location is predicted from the OTHER
locations to reduce self-fitting. Threshold classification requires user-selected
reference limits and is not a health-risk probability or a validated risk map.
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def predict_site_risks(samples, field, method, threshold, direction='Above', power=2.0,
                       lower=None, upper=None):
    if method not in ('IDW','Kriging'):
        raise ValueError('Method must be IDW or Kriging')
    if direction not in ('Above','Below','Outside range'):
        raise ValueError('Unknown threshold direction')
    if direction == 'Outside range':
        if lower is None or upper is None or not float(lower) < float(upper):
            raise ValueError('A valid lower and upper threshold is required')
    elif threshold is None or not np.isfinite(float(threshold)):
        raise ValueError('Enter a valid reference threshold')
    records = samples.copy()
    records[field] = pd.to_numeric(records[field], errors='coerce')
    records = records.loc[records[field].notna() & records.geometry.notna() &
                          ~records.geometry.is_empty &
                          (records.geometry.geom_type == 'Point')].copy()
    if len(records) < (6 if method == 'Kriging' else 4):
        raise ValueError(f'{method} leave-one-out prediction needs at least {6 if method == "Kriging" else 4} distinct valid sample sites')
    if records.crs is None:
        raise ValueError('Sampling CRS is missing')
    target_crs = records.estimate_utm_crs()
    if target_crs is None:
        raise ValueError('Unable to determine local projected CRS')
    projected = records.to_crs(target_crs)
    xy = np.array([(g.x,g.y) for g in projected.geometry], dtype=float)
    values = records[field].to_numpy(dtype=float)
    if not np.isfinite(xy).all() or np.unique(xy,axis=0).shape[0] != len(xy):
        raise ValueError('Duplicate or invalid sampling coordinates; aggregate or correct locations')
    prediction = np.full(len(values), np.nan, dtype=float)
    for i in range(len(values)):
        others = np.arange(len(values)) != i
        coords, vals = xy[others], values[others]
        if method == 'IDW':
            distances = np.linalg.norm(coords - xy[i], axis=1)
            weights = 1 / np.maximum(distances, 1e-8) ** float(power)
            prediction[i] = np.dot(weights, vals) / weights.sum()
        else:
            from pykrige.ok import OrdinaryKriging
            try:
                krige = OrdinaryKriging(coords[:,0],coords[:,1],vals,
                       variogram_model='spherical', verbose=False,
                       enable_plotting=False)
                p, _ = krige.execute('points',np.array([xy[i,0]]),np.array([xy[i,1]]))
                prediction[i] = float(np.asarray(p).ravel()[0])
            except Exception:
                # Do not misrepresent a fallback IDW estimate as Kriging.
                prediction[i] = np.nan
    def risky(values):
        if direction == 'Above': return values > float(threshold)
        if direction == 'Below': return values < float(threshold)
        return (values < float(lower)) | (values > float(upper))
    predicted = risky(prediction) & np.isfinite(prediction)
    observed = risky(values)
    output = records[[c for c in ('Site_ID','Site_Name','Latitude','Longitude') if c in records.columns]].copy()
    output['Observed_Value'] = values
    output[f'{method}_LOO_Prediction'] = prediction
    output['Observed_Exceeds_Threshold'] = observed
    output['Predicted_Exceeds_Threshold'] = predicted
    output['Prediction_Available'] = np.isfinite(prediction)
    return output, int(predicted.sum()), int(observed.sum()), int(np.isfinite(prediction).sum())
