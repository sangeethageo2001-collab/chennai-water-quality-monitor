# AquaSpatial 2.0 — Client-ready upgrade package

This package uses the **user-uploaded AquaSpatial source code**. Existing GIS workflows remain in place: BIS/WHO/US EPA screening, IDW and Kriging, site classification, leave-one-out screening, WQI/HPI/WPI, Piper Plot and PDF/PNG reporting.

## Changes in this package

- Transparent PM brand artwork at the **bottom-left of the login screen** (`pm_logo_transparent.png`). The image is embedded by `auth.py`, with no external image hosting.
- Aqua Ocean primary login button style and responsive logo dimensions.
- Additional user-facing caution around client uploads and threshold interpretation.
- `.gitignore` protects Streamlit password secrets, local virtual environments and generated data.
- `.streamlit/config.toml` supplies standard Aqua Ocean colors and matching upload size.
- All module names are normalized to the Python imports used by `app.py`.

## Before going live

1. Back up the currently deployed branch; test on an isolated branch and a separate Streamlit Cloud test app first.
2. Upload **all** the files from this folder to the root of the GitHub repository, preserving the `.streamlit` directory.
3. Set `app.py` as the Streamlit entry point and use the deployment's private **Secrets** editor for `[auth.users]` with generated hashes. Never publish `secrets.toml` or passwords.
4. Test the login, sample CSV and polygon upload, three reference frameworks, both interpolation methods, WQI/HPI/WPI, Piper Plot, report export, PNG map export, and logout.
5. Use a suitably restricted hosting plan and independent authentication for confidential client data. App-level Streamlit session login alone is not a substitute for audited enterprise authorization.

## Local run

```powershell
cd C:\Users\admin\Water_Toxicity_App
.\.venv314\Scripts\python.exe -m pip install -r requirements.txt
.\.venv314\Scripts\python.exe -m streamlit run app.py --server.port 8505
```

### Important scientific notes

- Map risk classes are **application-defined screening bands**, not WHO/BIS/US EPA-issued safety classifications.
- Leave-one-out predictions evaluate *existing sampling sites*; they do **not** locate new sampling points.
- PDF report thematic maps are generated server-side without satellite imagery. Browser PNG exports depend on map tile access, CORS and map loading.
- The uploaded reference presets must be checked against current regulatory guidance and analyte/units before client reporting.

**Validation performed:** Python parsing and syntax compilation of every Python file. GIS/browser map rendering, external tile services, installed package combinations and password login require your deployment test.
