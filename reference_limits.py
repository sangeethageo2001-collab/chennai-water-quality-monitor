"""Reference values for *screening* with BIS IS 10500:2012 acceptable-limit preset.

Only use for drinking-water screening, not surface water standards or a determination
of potability. Verify amendments, analytical speciation and units for each project.
Sources: https://cwc.gov.in/sites/default/files/status_trace_toxic_materials_indian_rivers.pdf
https://www.pib.gov.in/PressReleasePage.aspx?PRID=1843385
https://phedharyana.gov.in/Documents/UniformDrinkingWaterQualityMonitoringProtocol.pdf
"""
import pandas as pd

PRESET_NAME = "BIS IS 10500:2012 — acceptable limits (drinking-water screening)"
SOURCE_URL = "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1843385"

# Standard, ideal, lower, explanatory note. Concentrations mg/L unless noted.
# Chromium is treated as total Cr for this *specific* CWC table; confirm CSV speciation.
# Iron 0.30 is given in CWC's IS10500:2012 table. Published extracts/editions differ.
BIS_ACCEPTABLE = {
    "pH": (8.5, 7.0, 6.5, "pH range 6.5–8.5 (unitless)"),
    "TDS_mg_L": (500.0, 0.0, None, "Dissolved solids, mg/L"),
    "Turbidity_NTU": (1.0, 0.0, None, "Turbidity, NTU"),
    "Total_Hardness_mg_L": (200.0, 0.0, None, "Total hardness as CaCO3, mg/L"),
    "Alkalinity_mg_L": (200.0, 0.0, None, "Total alkalinity as CaCO3, mg/L"),
    "Chloride_mg_L": (250.0, 0.0, None, "Chloride as Cl, mg/L"),
    "Sulphate_mg_L": (200.0, 0.0, None, "Sulphate as SO4, mg/L"),
    "Nitrate_mg_L": (45.0, 0.0, None, "Nitrate as NO3, not NO3-N, mg/L"),
    "Fluoride_mg_L": (1.0, 0.0, None, "Fluoride as F, mg/L"),
    "Ca_mg_L": (75.0, 0.0, None, "Calcium as Ca, mg/L"),
    "Mg_mg_L": (30.0, 0.0, None, "Magnesium as Mg, mg/L"),
    "Pb_mg_L": (0.010, 0.0, None, "Lead as Pb, mg/L"),
    "Cd_mg_L": (0.003, 0.0, None, "Cadmium as Cd, mg/L"),
    "Cr_mg_L": (0.050, 0.0, None, "Chromium as Cr: confirm total-vs-Cr(VI) speciation"),
    "As_mg_L": (0.010, 0.0, None, "Total arsenic as As, mg/L"),
    "Hg_mg_L": (0.001, 0.0, None, "Mercury as Hg: confirm laboratory analyte"),
    "Ni_mg_L": (0.020, 0.0, None, "Nickel as Ni, mg/L"),
    "Cu_mg_L": (0.050, 0.0, None, "Copper as Cu, mg/L"),
    "Zn_mg_L": (5.0, 0.0, None, "Zinc as Zn, mg/L"),
    "Fe_mg_L": (0.30, 0.0, None, "Iron as Fe, mg/L; edition/amendment-dependent"),
    "Mn_mg_L": (0.10, 0.0, None, "Manganese as Mn, mg/L"),
}

# Normalized original CSV header aliases / simplified names.
ALIAS_TO_STANDARD = {
    "totalhardness": "Total_Hardness_mg_L", "totalhard": "Total_Hardness_mg_L",
    "hardness": "Total_Hardness_mg_L", "hardnessmgl": "Total_Hardness_mg_L",
    "alkalinity": "Alkalinity_mg_L", "alkalinitymgl": "Alkalinity_mg_L",
    "chloride": "Chloride_mg_L", "chloridem": "Chloride_mg_L", "chloridemgl": "Chloride_mg_L",
    "sulphate": "Sulphate_mg_L", "sulphatem": "Sulphate_mg_L", "sulphatemgl": "Sulphate_mg_L",
    "sulfate": "Sulphate_mg_L", "sulfatemgl": "Sulphate_mg_L",
    "nitrate": "Nitrate_mg_L", "nitratem": "Nitrate_mg_L", "nitratemg": "Nitrate_mg_L", "nitratemgl": "Nitrate_mg_L",
    "fluoride": "Fluoride_mg_L", "fluoridem": "Fluoride_mg_L", "fluoridemgl": "Fluoride_mg_L",
    "calcium": "Ca_mg_L", "magnesium": "Mg_mg_L",
    "turbidity": "Turbidity_NTU", "turbidityntu": "Turbidity_NTU", "turbiditym": "Turbidity_NTU",
}

def field_to_standard(field):
    import re
    normalized = re.sub(r"[^a-z0-9]", "", str(field).lower())
    for key in BIS_ACCEPTABLE:
        if re.sub(r"[^a-z0-9]", "", key.lower()) == normalized:
            return key
    return ALIAS_TO_STANDARD.get(normalized)

def preset_rows(columns, method):
    rows, omitted = [], []
    for col in columns:
        match = field_to_standard(col)
        if match is None or match not in BIS_ACCEPTABLE:
            omitted.append(col)
            continue
        standard, ideal, lower, note = BIS_ACCEPTABLE[match]
        rows.append({"Parameter": col, "Standard": standard, "Ideal": ideal,
                     "Lower": lower, "Weight": None})
    return rows, omitted

def reference_dataframe(columns, method):
    rows, omitted = preset_rows(columns, method)
    return pd.DataFrame(rows, columns=["Parameter", "Standard", "Ideal", "Lower", "Weight"]), omitted
