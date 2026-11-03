"""Conservative WHO GDWQ 2022 guideline preset for drinking-water *screening*.

Not all WHO guidance is a health-based numeric value. Only explicitly covered
analytes are autofilled. Check edition, species, and units with laboratory data.
Source: https://www.who.int/publications/i/item/9789240045064
"""
from __future__ import annotations
import pandas as pd

WHO_NAME = "WHO GDWQ 2022 — selected health-based values"
WHO_SOURCE = "https://www.who.int/publications/i/item/9789240045064"
# Standard, Ideal, Lower, note. mg/L, nitrate as NO3, fluoride as F.
WHO_GUIDELINES = {
    'Pb_mg_L': (0.010, 0., None, 'Lead; provisional/achievability considerations'),
    'Cd_mg_L': (0.003, 0., None, 'Cadmium'),
    'Cr_mg_L': (0.050, 0., None, 'Total chromium only'),
    'As_mg_L': (0.010, 0., None, 'Arsenic, provisional'),
    'Hg_mg_L': (0.006, 0., None, 'INORGANIC mercury ONLY; not automatically suitable for total Hg'),
    'Ni_mg_L': (0.070, 0., None, 'Nickel'),
    'Cu_mg_L': (2.0, 0., None, 'Copper'),
    'Mn_mg_L': (0.080, 0., None, 'Total manganese, provisional'),
    'Fluoride_mg_L': (1.5, 0., None, 'Fluoride as F'),
    'Nitrate_mg_L': (50.0, 0., None, 'Nitrate as NO3; NOT nitrate-N'),
}
# Do not automatically match Hg_mg_L because the CSV may be total Hg.
WHO_REQUIRES_SPECIES_CONFIRMATION = {'Hg_mg_L'}

def who_standard(field):
    if field not in WHO_GUIDELINES or field in WHO_REQUIRES_SPECIES_CONFIRMATION:
        return None
    return field

def who_reference_dataframe(columns, method):
    rows, omitted = [], []
    for field in columns:
        if who_standard(field) is None:
            omitted.append(field)
            continue
        limit, ideal, lower, _ = WHO_GUIDELINES[field]
        rows.append({'Parameter': field, 'Standard': limit, 'Ideal': ideal,
                     'Lower': lower, 'Weight': None})
    return pd.DataFrame(rows, columns=['Parameter','Standard','Ideal','Lower','Weight']), omitted
