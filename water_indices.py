"""Configurable, complete-case water quality/pollution indices for uploaded GIS samples.

No regulatory limits are supplied by the application. The user must choose and document
reference values appropriate to waterbody and beneficial use before interpretation.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

METAL_COLUMNS = {"Pb_mg_L", "Cd_mg_L", "Cr_mg_L", "As_mg_L", "Hg_mg_L", "Ni_mg_L", "Cu_mg_L", "Zn_mg_L", "Fe_mg_L", "Mn_mg_L"}
SPECIAL_COLUMNS = {"pH", "DO_mg_L"}


def calculate_indices(samples: pd.DataFrame, method: str, reference: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Return dimensionless per-row index and diagnostic table.

    reference columns: Parameter, Standard, Ideal, Lower, Weight.
    WQI: weighted arithmetic quality ratings; default weight 1/standard.
    HPI: weighted heavy-metal index, quality rating 100*abs(C-I)/(S-I), weight 1/S.
    WPI: user-configured arithmetic mean of quality ratios (Q_i/100); this is a
         declared operational convention, NOT a universal standardized WPI.

    All selected analytes must be present and finite per location; incomplete cases -> NaN.
    """
    if method not in {"WQI", "HPI", "WPI"}:
        raise ValueError("Choose WQI, HPI, or WPI")
    expected = ["Parameter", "Standard", "Ideal", "Lower", "Weight"]
    if any(k not in reference.columns for k in expected):
        raise ValueError(f"Reference table must contain {', '.join(expected)}")
    spec = reference.copy()
    spec["Parameter"] = spec["Parameter"].astype(str)
    if spec["Parameter"].duplicated().any():
        raise ValueError("Each parameter must have exactly one reference row")
    if method == "HPI" and any(c not in METAL_COLUMNS for c in spec["Parameter"]):
        raise ValueError("HPI uses heavy-metal parameters only")
    minimum = 3 if method == "WQI" else 2
    if len(spec) < minimum:
        raise ValueError(f"{method} requires at least {minimum} parameters with configured standards")
    for name in ["Standard", "Ideal", "Lower", "Weight"]:
        spec[name] = pd.to_numeric(spec[name], errors="coerce")
    if spec["Standard"].isna().any() or (spec["Standard"] <= 0).any():
        raise ValueError("Supply a positive Standard limit for every selected parameter")
    if spec["Weight"].notna().any() and (spec["Weight"].dropna() <= 0).any():
        raise ValueError("Weights must be positive, or left blank to use inverse-standard weights")
    columns = spec["Parameter"].tolist()
    absent = [c for c in columns if c not in samples.columns]
    if absent:
        raise ValueError("Missing parameter columns: " + ", ".join(absent))
    values = samples[columns].apply(pd.to_numeric, errors="coerce")
    valid = values.notna().all(axis=1) & np.isfinite(values).all(axis=1)
    valid &= (values >= 0).all(axis=1) if "pH" not in columns else (values.drop(columns=["pH"]) >= 0).all(axis=1)
    score = pd.Series(np.nan, index=samples.index, dtype=float, name=method)
    if not valid.any():
        raise ValueError("No sample has complete numeric observations for all selected parameters")
    data = values.loc[valid]
    terms = []
    weights = []
    for row in spec.itertuples(index=False):
        col = row.Parameter
        standard = float(row.Standard)
        ideal = 0.0 if pd.isna(row.Ideal) else float(row.Ideal)
        lower = float(row.Lower) if not pd.isna(row.Lower) else np.nan
        x = data[col].astype(float)
        if method == "HPI":
            if standard <= ideal:
                raise ValueError(f"{col}: HPI Standard must exceed Ideal")
            q = 100 * (x - ideal).abs() / (standard - ideal)
        elif col == "pH":
            # Two-sided deviation from pH=7 when a lower limit is provided.
            if not np.isfinite(lower) or not (lower < 7 < standard):
                raise ValueError("pH requires Lower < 7 and Standard (upper) > 7")
            q = 100 * np.where(x < 7, (7 - x) / (7 - lower), (x - 7) / (standard - 7))
        elif col == "DO_mg_L":
            # DO lower objective (Standard), ideal 14.6 mg/L in WAWQI convention.
            ideal = 14.6 if pd.isna(row.Ideal) else ideal
            if standard >= ideal:
                raise ValueError("DO Standard must be below Ideal (e.g., the 14.6 mg/L convention)")
            q = 100 * np.maximum(0, ideal - x) / (ideal - standard)
        else:
            if standard <= ideal:
                raise ValueError(f"{col}: Standard must exceed Ideal")
            q = 100 * np.maximum(0, x - ideal) / (standard - ideal)
        terms.append(np.asarray(q, dtype=float))
        weight = float(row.Weight) if not pd.isna(row.Weight) else (1.0 / standard)
        weights.append(weight)
    q_matrix = np.column_stack(terms)
    w = np.asarray(weights, dtype=float)
    if method == "WPI":
        # Operational WPI, explicitly defined as mean quality ratio, unweighted.
        computed = q_matrix.mean(axis=1) / 100.0
    else:
        computed = np.average(q_matrix, axis=1, weights=w)
    score.loc[valid] = computed
    detail = samples[[c for c in ("Site_ID", "Site_Name", "Latitude", "Longitude") if c in samples]].copy()
    detail[method] = score
    detail["Parameters_Used"] = ", ".join(columns)
    detail["Complete_Case"] = valid
    return score, detail
