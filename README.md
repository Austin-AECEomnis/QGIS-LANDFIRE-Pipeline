# 🔥 LANDFIRE Acquisition Pipeline

## 📋 Table of Contents
- [Overview](#overview)
- [Why This Matters](#why-this-matters)
- [How It Works](#how-it-works)
- [Band Structure](#band-structure)
- [Architecture Decision Log](#architecture-decision-log)
- [Repository Structure](#repository-structure)
- [Configuration](#configuration)
- [Technologies Used](#technologies-used)

---

## 🌐 Overview

Automated Python pipeline that submits jobs to the USGS LANDFIRE Product Service (LFPS) v2 API, polls for completion, downloads and extracts the result, embeds categorical Raster Attribute Tables (RATs) directly into the output file, and runs a pixel-level co-registration verification across all bands before delivering a single verified GeoTIFF ready for fire behavior modeling or spatial analysis.

Designed to run from the QGIS Python Editor panel. All dependencies (GDAL, requests, numpy) are bundled with the standard QGIS 3.x installation. No additional package installation required.

Output: an 11-band GeoTIFF in EPSG:5070 (NAD83 / Conus Albers) matching the 11 fire-behavior-relevant bands of an IFTDSS landscape export, with categorical RATs embedded on the FBFM40, EVT, EVC, and EVH bands so ArcGIS Pro and QGIS display category names natively without a separate join or reclassification step.

---

## ⚠️ Why This Matters

LANDFIRE data is the foundational input layer for every major operational fire behavior modeling platform in the United States, including IFTDSS, WFDSS, FlamMap, and FARSITE. Acquiring it programmatically rather than through a GUI eliminates manual steps, enables repeatable batch pulls across multiple AOIs, and produces a locally verified output file with attribution information embedded rather than left as a separate lookup table.

The LFPS API underwent a silent, undocumented migration from its legacy v1 GP Server architecture to a new v2 REST API around May 2025. The documented endpoint pattern referenced in LANDFIRE's own materials and implemented by third-party packages including `landfire-python` and `rlandfire` no longer works. This pipeline was built using the v2 API, reverse-engineered from live service behavior and independently confirmed through the `rlandfire` package changelog.

See `docs/api_discovery.md` for the full discovery log, including verified endpoint parameters, field names, and status string corrections.

---

## ⚙️ How It Works

The pipeline operates in five stages:

**1. Job Submission**
A Python script posts a job payload to the LFPS v2 API at `https://lfps.usgs.gov/api/job/submit`. The payload specifies the layer list (semicolon-delimited LANDFIRE product codes), area of interest (space-separated WSEN bounding box in WGS84), email address (required by the v2 API), and output projection (EPSG:5070 to force a fixed CRS rather than the per-AOI localized Albers default). The API returns a job ID.

**2. Status Polling**
The script polls `https://lfps.usgs.gov/api/job/status` on a 5-second interval until the job reaches `Succeeded` status. On completion the status response includes a direct download URL for the output zip file.

**3. Download and Extraction**
The output directory is wiped and rebuilt fresh on each run. The zip is downloaded in streaming chunks and extracted, producing a single multi-band GeoTIFF named after the job GUID. The script confirms exactly one `.tif` file is present before proceeding.

**4. Raster Attribute Table Embedding**
For each categorical band (FBFM40, EVT, EVC, EVH), the pipeline fetches the matching LANDFIRE attribute CSV from the LANDFIRE server, parses it, and writes a proper GDAL Raster Attribute Table directly into the GeoTIFF in update mode. The label column is detected dynamically from the CSV schema so the same function handles all LANDFIRE categorical products regardless of differing column naming conventions.

**5. Co-registration Verification**
The pipeline reads every band's pixel array, builds a NoData mask for each, and compares all bands against band 1 using numpy array equality. A mismatch raises a RuntimeError and halts the pipeline before a misaligned file propagates into fire behavior modeling inputs. The check is proven against AOIs with real NoData edges, where 801,651 offshore Gulf water pixels matched identically across all 11 bands.

---

## 🗺️ Band Structure

The 11-band output matches the fire-behavior-relevant content of an IFTDSS landscape export. The only band not replicated is IFTDSS Band 12 (LANDFIRE Map Zone), an administrative processing grid with no fire modeling use that is not available as a standard LFPS product.

| Band | Layer Code | Product | Type | RAT Embedded |
|---|---|---|---|---|
| 1 | LF2020_Elev | Elevation | Continuous (meters) | No |
| 2 | LF2020_SlpD | Slope | Continuous (degrees) | No |
| 3 | LF2020_Asp | Aspect | Continuous (degrees) | No |
| 4 | LF2024_FBFM40 | 40 Scott and Burgan Fire Behavior Fuel Models | Categorical | Yes (46 classes) |
| 5 | LF2024_CC | Forest Canopy Cover | Continuous (%) | No |
| 6 | LF2024_CH | Forest Canopy Height | Continuous (meters) | No |
| 7 | LF2024_CBH | Forest Canopy Base Height | Continuous (meters) | No |
| 8 | LF2024_CBD | Forest Canopy Bulk Density | Continuous (kg/m3) | No |
| 9 | LF2024_EVT | Existing Vegetation Type | Categorical | Yes (1069 classes) |
| 10 | LF2024_EVC | Existing Vegetation Cover | Categorical | Yes (293 classes) |
| 11 | LF2024_EVH | Existing Vegetation Height | Categorical | Yes (162 classes) |

All bands are 30-meter resolution, 16-bit signed integer, pixel-interleaved, EPSG:5070 (NAD83 / Conus Albers), NoData value -9999.

---

## 🏗️ Architecture Decision Log

Multiple decisions were evaluated and documented during development. This log records the reasoning behind each one.

**Decision 1: Output_Projection parameter**
Without an explicit `Output_Projection` parameter, LFPS returns a custom Albers Conical Equal Area projection centered on the submitted AOI's bounding box coordinates. This produces a different CRS definition on every pull. Any pipeline assuming a consistent CRS breaks on the second run. Setting `Output_Projection` to `5070` forces all output to the standard LANDFIRE native projection (NAD83 / Conus Albers), confirmed by direct GDAL inspection of the downloaded raster WKT. This parameter is now locked into the production payload permanently.

**Decision 2: RAT embedding over external lookup table**
The LANDFIRE FAQ documents a manual workflow: download the CSV, build a raster attribute table inside the GIS application, join on VALUE, export to make the join permanent. That workflow requires manual steps on every new file. Embedding the RAT directly into the GeoTIFF via GDAL in update mode means the category names travel with the file permanently. ArcGIS Pro and QGIS read them natively without any join step. This also resolves the IFTDSS-documented problem of LFPS outputs displaying as grayscale in GIS — the embedded RAT provides the category information the renderer needs.

**Decision 3: GeoTIFF over LCP format**
The legacy fire behavior model input format was a binary `.LCP` file with a 7,316-byte header. In 2024, LANDFIRE and the USFS Fire Sciences Lab completed a coordinated transition from `.LCP` to GeoTIFF as the native landscape format for FlamMap, FARSITE, FSPro, and RANDIG. The LFPS itself now delivers GeoTIFF rather than `.LCP`. No conversion step is needed. The 11-band GeoTIFF produced by this pipeline is the current native landscape format for operational fire behavior modeling.

**Decision 4: Dynamic label column detection**
LANDFIRE categorical CSVs do not share a consistent schema. FBFM40 uses `FBFM40` as its label column, EVT uses `EVT_SBCLS`, and EVC and EVH both use `CLASSNAMES`. Hardcoding any one column name into the RAT embedding function would require a code change each time a new categorical band is added. The label column is instead detected dynamically as the last column before the `R` column in each CSV, making the function schema-agnostic across all LANDFIRE categorical products.

**Decision 5: Output directory wipe on each run**
LFPS names output files after the job GUID, so filenames never naturally collide between runs. Without an explicit wipe step, every run accumulates a new set of files in the output directory. A downstream step opening the most recent `.tif` by filename sort could silently pick up a stale file if the new job failed mid-download. The directory is wiped and rebuilt at the start of each download step so the output folder always contains exactly one pull: the current verified run.

---

## 📁 Repository Structure

```
QGIS-LANDFIRE-Pipeline/
├── landfire_pipeline.py    # Production pipeline script — submit, poll,
│                           # download, RAT embed, co-registration verify
├── .gitignore              # Excludes GeoTIFF outputs (regenerable on demand)
├── RawData/                # Output directory for downloaded rasters
│   └── .gitkeep            # Preserves folder in version control
├── Processed/              # Output directory for derived products
│   └── .gitkeep
└── docs/
    └── api_discovery.md    # LFPS v1 to v2 migration discovery log,
                            # verified endpoint parameters, and layer codes
```

---

## 🔧 Configuration

Open `landfire_pipeline.py` and edit the three values in the `CONFIGURATION` section at the top of the file before running:

```python
AREA_OF_INTEREST = "-98.85 29.75 -98.65 29.95"  # W S E N in WGS84
EMAIL = "your@email.com"                          # Required by LFPS v2 API
OUTPUT_DIR = r"C:\your\output\path"               # Local output directory
```

All other constants (endpoints, layer codes, CSV URLs, projection) are stable and do not require editing unless LANDFIRE publishes a new data version.

To update to a newer LANDFIRE data version, replace the version year in the layer codes in `LAYER_LIST` (e.g., `LF2024_FBFM40` becomes `LF2025_FBFM40`) and update the matching CSV URLs in `RAT_LAYERS` to the new version path on `landfire.gov`.

---

## 🛠️ Technologies Used

- Python 3.12 (QGIS bundled environment)
- GDAL 3.12.4 (via QGIS bundled osgeo)
- requests 2.33.1 (QGIS bundled)
- numpy (QGIS bundled)
- USGS LANDFIRE Product Service (LFPS) v2 REST API
- LANDFIRE 2024 Update (LF 2024, version 2.5.0)
- EPSG:5070 — NAD83 / Conus Albers (NAD83, Albers Equal Area)
- QGIS 3.44.10 LTR

---

*Austin Addington Berlin | AECE Omnis LLC | github.com/Austin-AECEomnis | aeceomnis.com*
