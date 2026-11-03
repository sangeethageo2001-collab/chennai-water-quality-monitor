"""Selected USEPA drinking-water screening references; checked November 2026.

Primary numeric MCLs (health-based enforceable drinking-water regulations) are
separated from non-enforceable secondary guidelines. Values in mg/L except pH.

Lead and copper: NOT assigned automatically because EPA uses special treatment-
technique/action-level rules, not an ordinary single-sample MCL.
Mercury: inorganic species only, cannot assume a total-mercury CSV matches.
Nitrate: dataset presumed nitrate as NO3, converted from 10 mg/L nitrate-N.
"""
import pandas as pd
from reference_limits import field_to_standard

EPA_NAME = "US EPA drinking-water — selected primary MCLs and secondary guidelines"
EPA_SOURCE = "https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations"
EPA_SECONDARY_SOURCE = "https://www.epa.gov/sdwa/drinking-water-regulations-and-contaminants"

# (upper reference, ideal, lower reference, description, type)
# Regulatory primaries distinct from aesthetic secondary values.
EPA_LIMITS = {
 "As_mg_L": (0.010, 0.0, None, "Arsenic as As", "Primary MCL"),
 "Cd_mg_L": (0.005, 0.0, None, "Cadmium", "Primary MCL"),
 "Cr_mg_L": (0.100, 0.0, None, "Total chromium", "Primary MCL"),
 "Fluoride_mg_L": (4.0, 0.0, None, "Fluoride primary standard; secondary is 2.0 mg/L", "Primary MCL"),
 "Nitrate_mg_L": (10.0 * 62.0049 / 14.0067, 0.0, None, "Nitrate as NO3 (converted from 10 mg/L as nitrogen)", "Primary MCL"),
 "pH": (8.5, 7.0, 6.5, "pH 6.5–8.5", "Secondary"),
 "TDS_mg_L": (500.0, 0.0, None, "Total dissolved solids", "Secondary"),
 "Chloride_mg_L": (250.0, 0.0, None, "Chloride", "Secondary"),
 "Sulphate_mg_L": (250.0, 0.0, None, "Sulfate", "Secondary"),
 "Zn_mg_L": (5.0, 0.0, None, "Zinc", "Secondary"),
 "Fe_mg_L": (0.3, 0.0, None, "Iron", "Secondary"),
 "Mn_mg_L": (0.05, 0.0, None, "Manganese", "Secondary"),
}
# These should NEVER use the wrong analyte species or a regulatory action level.
EXCLUDED_AUTOMATIC = {"Pb_mg_L", "Cu_mg_L", "Hg_mg_L"}

def epa_standard(field):
    match = field_to_standard(field)
    return match if match in EPA_LIMITS and match not in EXCLUDED_AUTOMATIC else None

def epa_limit_note(field):
    match=epa_standard(field)
    if not match: return "No automatically applicable US EPA numeric reference."
    upper, ideal, lower, detail, category = EPA_LIMITS[match]
    return f"{category}: {detail}; reference {upper:.4g} mg/L" if match != "pH" else f"Secondary pH recommended interval {lower}–{upper}"

def epa_reference_dataframe(columns, method):
    rows, omitted = [], []
    for col in columns:
        match=epa_standard(col)
        if match is None:
            omitted.append(col)
            continue
        standard, ideal, lower, detail, category = EPA_LIMITS[match]
        rows.append({"Parameter": col, "Standard": standard, "Ideal": ideal,
                     "Lower": lower, "Weight": None})
    return pd.DataFrame(rows, columns=["Parameter","Standard","Ideal","Lower","Weight"]), omitted
