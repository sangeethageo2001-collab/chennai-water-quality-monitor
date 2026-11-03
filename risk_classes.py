"""Shared screening classification for site observations and interpolation grids.
WHO/BIS furnish applicable constituent LIMITS; three screening bands are app-defined.
"""
import numpy as np

RISK_COLORS = {"No risk flag": "#22c55e", "Moderate": "#facc15", "High": "#ef4444"}

def classify(values, threshold, direction="Above", lower=None, moderate_fraction=0.75):
    a = np.asarray(values, dtype=float)
    if not (0 < moderate_fraction < 1):
        raise ValueError("Moderate fraction must be between 0 and 1")
    threshold = float(threshold)
    if not np.isfinite(threshold):
        raise ValueError("Screening threshold must be finite")
    result = np.full(a.shape, "Unavailable", dtype=object)
    valid = np.isfinite(a)
    if direction == "Above":
        high = valid & (a > threshold)
        moderate = valid & (a >= threshold * moderate_fraction) & ~high
    elif direction == "Below":
        if threshold <= 0: raise ValueError("Below-type threshold must be positive")
        high = valid & (a < threshold)
        moderate = valid & (a <= threshold / moderate_fraction) & ~high
    elif direction == "Outside range":
        if lower is None or not float(lower) < threshold:
            raise ValueError("Two-sided limits must have lower < upper")
        lower = float(lower)
        high = valid & ((a < lower) | (a > threshold))
        margin = (threshold - lower) * (1 - moderate_fraction)
        moderate = valid & ((a <= lower + margin) | (a >= threshold - margin)) & ~high
    else:
        raise ValueError(f"Unknown screening direction: {direction}")
    result[valid] = "No risk flag"
    result[moderate] = "Moderate"
    result[high] = "High"
    return result
