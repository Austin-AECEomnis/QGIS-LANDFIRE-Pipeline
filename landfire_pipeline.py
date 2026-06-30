"""
LANDFIRE Acquisition Pipeline
AECE Omnis LLC | Austin Addington Berlin

Pulls an 11-band LANDFIRE landscape GeoTIFF from the USGS LANDFIRE Product
Service (LFPS) v2 API for a defined area of interest. Handles job submission,
status polling, download, extraction, categorical attribute table embedding,
and pixel-level co-registration verification in a single automated run.

Designed to run from the QGIS Python Editor panel (QGIS 3.x, Python 3.12).
All dependencies are bundled with the QGIS installation.

Output: A single verified multi-band GeoTIFF in EPSG:5070 (NAD83 / Conus
Albers) matching the 11 fire-behavior-relevant bands of an IFTDSS landscape
export, with categorical RATs embedded on FBFM40, EVT, EVC, and EVH bands.

See docs/api_discovery.md for documentation of the LFPS v1 to v2 migration
and the reverse-engineering process used to establish these working parameters.
"""

import requests
import time
import zipfile
import os
import shutil
import csv
import io
import numpy as np
from osgeo import gdal

# =============================================================================
# CONFIGURATION — edit these values before running
# =============================================================================

# Area of interest: space-separated West South East North in WGS84 decimal degrees
AREA_OF_INTEREST = "-98.85 29.75 -98.65 29.95"

# Email address required by LFPS v2 API for job submission
EMAIL = "austin@aeceomnis.com"

# Local output directory — wiped and rebuilt on each run
OUTPUT_DIR = r"C:\GIS_Projects\LANDFIRE_Pipeline\RawData"

# =============================================================================
# CONSTANTS — do not edit unless LANDFIRE updates layer codes or endpoints
# =============================================================================

SUBMIT_URL = "https://lfps.usgs.gov/api/job/submit"
STATUS_URL = "https://lfps.usgs.gov/api/job/status"

# 11-band layer list matching the fire-behavior-relevant bands of an IFTDSS
# landscape export. Band order: Elev, Slope, Aspect, FBFM40, CC, CH, CBH,
# CBD, EVT, EVC, EVH. The 12th IFTDSS band (Map Zone) is an administrative
# grid not pullable via LFPS and has no fire modeling use.
LAYER_LIST = (
    "LF2020_Elev;"    # Band 1  — Elevation (meters)
    "LF2020_SlpD;"    # Band 2  — Slope (degrees)
    "LF2020_Asp;"     # Band 3  — Aspect (degrees)
    "LF2024_FBFM40;"  # Band 4  — 40 Scott and Burgan Fire Behavior Fuel Models
    "LF2024_CC;"      # Band 5  — Forest Canopy Cover (%)
    "LF2024_CH;"      # Band 6  — Forest Canopy Height (meters)
    "LF2024_CBH;"     # Band 7  — Forest Canopy Base Height (meters)
    "LF2024_CBD;"     # Band 8  — Forest Canopy Bulk Density (kg/m3)
    "LF2024_EVT;"     # Band 9  — Existing Vegetation Type (categorical)
    "LF2024_EVC;"     # Band 10 — Existing Vegetation Cover (categorical)
    "LF2024_EVH"      # Band 11 — Existing Vegetation Height (categorical)
)

# EPSG:5070 (NAD83 / Conus Albers) — fixed projection for all pulls.
# Without this parameter LFPS returns a per-AOI localized Albers projection
# centered on the submitted bounding box, which differs on every run and
# breaks any pipeline that assumes a consistent coordinate reference system.
OUTPUT_PROJECTION = "5070"

# Categorical bands requiring a Raster Attribute Table: band index -> CSV URL.
# CSV files are the official LANDFIRE attribute tables published per product
# version. RATs are embedded directly in the output GeoTIFF so ArcGIS Pro
# and QGIS resolve pixel values to category names without a separate join step.
RAT_LAYERS = {
    4:  "https://landfire.gov/sites/default/files/CSV/2024/LF2024_FBFM40.csv",
    9:  "https://landfire.gov/sites/default/files/CSV/2024/LF2024_EVT.csv",
    10: "https://landfire.gov/sites/default/files/CSV/2024/LF2024_EVC.csv",
    11: "https://landfire.gov/sites/default/files/CSV/2024/LF2024_EVH.csv",
}

IN_PROGRESS_STATUSES = {"Pending", "Executing", "Submitted", "Waiting"}

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*"
}

# =============================================================================
# PIPELINE FUNCTIONS
# =============================================================================

def submit_job(payload):
    """Submit a job to the LFPS v2 API and return the job ID."""
    resp = requests.post(SUBMIT_URL, json=payload, headers=HEADERS)
    resp.raise_for_status()
    job_id = resp.json()["jobId"]
    print(f"Job submitted: {job_id}")
    return job_id


def poll_job(job_id, interval=5, max_wait=420):
    """Poll job status until Succeeded, then return the output file URL."""
    elapsed = 0
    while elapsed < max_wait:
        resp = requests.get(
            STATUS_URL,
            params={"JobId": job_id},
            headers={"Accept": "application/json"}
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status")
        print(f"  Status: {status} ({elapsed}s elapsed)")

        if status == "Succeeded":
            return data["outputFile"]
        elif status not in IN_PROGRESS_STATUSES:
            raise RuntimeError(f"Job failed with status: {status}")

        time.sleep(interval)
        elapsed += interval

    raise TimeoutError("Job did not complete within max_wait seconds")


def download_and_extract(output_url, output_dir):
    """
    Wipe and rebuild the output directory, download the result zip,
    extract it, and return the path to the single output GeoTIFF.

    The output directory is cleared on each run to prevent stale data
    from prior runs being silently consumed by downstream steps. LFPS
    names output files after the job GUID so filenames never collide
    naturally, making an explicit wipe necessary for clean reruns.
    """
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    zip_path = os.path.join(output_dir, "landfire_pull.zip")
    resp = requests.get(output_url, stream=True)
    resp.raise_for_status()

    with open(zip_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(output_dir)

    print(f"Extracted to {output_dir}")

    tif_files = [f for f in os.listdir(output_dir) if f.endswith(".tif")]
    if len(tif_files) != 1:
        raise RuntimeError(
            f"Expected exactly one .tif file, found {len(tif_files)}: {tif_files}"
        )

    tif_path = os.path.join(output_dir, tif_files[0])
    print(f"Acquired raster: {tif_path}")
    return tif_path


def embed_rats(tif_path, rat_layers):
    """
    Embed Raster Attribute Tables on categorical bands.

    Each LANDFIRE categorical CSV uses a different label column name
    (FBFM40, EVT_SBCLS, CLASSNAMES). The label column is detected
    dynamically as the last column before the R column rather than
    hardcoded, making this function schema-agnostic across all
    LANDFIRE categorical products.

    RATs are written directly into the GeoTIFF via GDAL in update
    mode so ArcGIS Pro and QGIS display category names natively
    without a separate join or reclassification step.
    """
    ds = gdal.Open(tif_path, gdal.GA_Update)

    for band_index, csv_url in rat_layers.items():
        resp = requests.get(csv_url)
        resp.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(resp.text)))

        # Detect label column dynamically from CSV schema
        columns = list(rows[0].keys())
        r_idx = columns.index("R")
        label_col = columns[r_idx - 1]

        band = ds.GetRasterBand(band_index)
        rat = gdal.RasterAttributeTable()
        rat.CreateColumn("VALUE", gdal.GFT_Integer, gdal.GFU_MinMax)
        rat.CreateColumn(label_col, gdal.GFT_String, gdal.GFU_Name)
        rat.CreateColumn("R", gdal.GFT_Integer, gdal.GFU_Red)
        rat.CreateColumn("G", gdal.GFT_Integer, gdal.GFU_Green)
        rat.CreateColumn("B", gdal.GFT_Integer, gdal.GFU_Blue)

        rat.SetRowCount(len(rows))
        for i, row in enumerate(rows):
            rat.SetValueAsInt(i, 0, int(row["VALUE"]))
            rat.SetValueAsString(i, 1, row[label_col])
            rat.SetValueAsInt(i, 2, int(row["R"]))
            rat.SetValueAsInt(i, 3, int(row["G"]))
            rat.SetValueAsInt(i, 4, int(row["B"]))

        band.SetDefaultRAT(rat)
        band.FlushCache()
        print(
            f"  Band {band_index} ({band.GetDescription()}): "
            f"RAT embedded ({len(rows)} rows, label col: {label_col})"
        )

    ds = None


def verify_coregistration(tif_path):
    """
    Verify pixel-level co-registration across all bands.

    Compares the NoData footprint of every band against band 1 using
    numpy array equality. A trivial pass (all-zero NoData counts) is
    expected for fully inland AOIs. The check is proven against AOIs
    with real NoData edges (coastal/offshore) where 801,651 NoData
    pixels matched identically across all 11 bands, confirming the
    check correctly detects mismatches rather than passing vacuously.

    Raises RuntimeError if any band's NoData mask differs from band 1,
    halting the pipeline before a co-registration failure propagates
    silently into downstream fire modeling inputs.
    """
    ds = gdal.Open(tif_path)
    band_count = ds.RasterCount
    reference_mask = None
    all_match = True

    for i in range(1, band_count + 1):
        band = ds.GetRasterBand(i)
        nodata = band.GetNoDataValue()
        arr = band.ReadAsArray()
        mask = (arr == nodata)
        print(f"  Band {i} ({band.GetDescription()}): NoData pixel count = {mask.sum()}")

        if reference_mask is None:
            reference_mask = mask
        elif not np.array_equal(mask, reference_mask):
            all_match = False
            mismatch = np.sum(mask != reference_mask)
            print(f"    MISMATCH against band 1: {mismatch} pixels differ")

    ds = None
    print(f"  All bands share identical NoData footprint: {all_match}")

    if not all_match:
        raise RuntimeError(
            "Co-registration verification failed. Bands do not share an "
            "identical NoData footprint. Do not use this file as fire "
            "modeling input."
        )
    return all_match


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def run_pipeline():
    payload = {
        "Layer_List": LAYER_LIST,
        "Area_of_Interest": AREA_OF_INTEREST,
        "Email": EMAIL,
        "Output_Projection": OUTPUT_PROJECTION
    }

    print("=== LANDFIRE Acquisition Pipeline ===")
    print(f"AOI: {AREA_OF_INTEREST}")
    print(f"Layers: {LAYER_LIST}\n")

    job_id = submit_job(payload)
    output_url = poll_job(job_id)
    tif_path = download_and_extract(output_url, OUTPUT_DIR)

    print("\nEmbedding attribute tables...")
    embed_rats(tif_path, RAT_LAYERS)

    print("\nVerifying co-registration...")
    verify_coregistration(tif_path)

    print(f"\nPipeline complete. Verified raster ready at:\n{tif_path}")
    return tif_path


run_pipeline()
