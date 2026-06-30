# LFPS v1 to v2 API Migration — Discovery Log

**AECE Omnis LLC | Austin Addington Berlin**

This document records the discovery process that identified a silent migration of the LANDFIRE Product Service (LFPS) REST API from its legacy v1 GP Server pattern to an undocumented v2 endpoint, and the systematic reverse-engineering that produced the working parameters now used in this pipeline.

---

## Background

The LANDFIRE Product Service (LFPS) is a USGS-operated REST API for programmatic acquisition of LANDFIRE geospatial data products. Prior to approximately May 2025, LFPS exposed a standard ArcGIS GP Server `submitJob` endpoint documented in LANDFIRE's official materials and implemented by third-party packages including `landfire-python` (Python) and `landfireAPI()` in the `rlandfire` R package.

---

## The Problem

On first scripted attempt, a GET request to the documented `submitJob` GP Server endpoint returned the live website's full HTML application rather than a JSON job response. Systematic isolation ruled out two candidate causes:

A plain metadata GET against the same base service returned clean JSON, confirming the service was reachable and that bot detection or User-Agent filtering was not the issue. Switching from GET to POST against the same endpoint returned the same HTML, ruling out an HTTP method mismatch.

Pulling the live parameter list directly from the GP service's own info endpoint revealed the real cause: the `Email` parameter shown on the public web form was absent from the actual GP task definition, and an undocumented `API_Job_ID` parameter was present instead. This confirmed the public website's backend had migrated to a new submission architecture that no longer exposed the classic GP REST contract directly.

---

## Independent Confirmation

The R package `rlandfire` independently confirmed the finding. Its `landfireAPI()` function is explicitly marked superseded due to LFPS API updates, replaced by `landfireAPIv2()`, with `Email` stated as a required argument for the v2 API specifically and a dated warning that workflows built before May 2025 require updating.

This validated the issue as a real, dated, agency-side API migration rather than any error in the request construction, and established approximately May 2025 as the migration date.

---

## Reverse Engineering the v2 Endpoint

With no public documentation for the v2 API, the endpoint structure was reverse-engineered in two steps.

**Step 1 — Endpoint and headers.** A browser-based AI assistant in Chrome DevTools was used to submit the live LFPS web form and surface the real submission endpoint URL, HTTP method, and Content-Type headers: `POST https://lfps.usgs.gov/api/job/submit`, `Content-Type: application/json`.

**Step 2 — Field names from validation errors.** The DevTools assistant's inferred field names (camelCase: `layerList`, `areaOfInterest`, `email`) were incorrect. Submitting a payload with these names returned a structured 400 validation error that explicitly named the correct required parameters: `Layer_List`, `Area_of_Interest`, `Email`. The original underscore-and-capital-case convention from the legacy GP service had been preserved in the v2 API despite the endpoint change. Correcting the payload to match produced a clean 200 response with a real job ID.

**Step 3 — Status endpoint.** Candidate status URL patterns were tested directly. The URL returning a structured JSON error (rather than a 404) was identified as the live endpoint. That error named the correct query parameter casing (`JobId`), which on retry returned a complete job status payload including a `Succeeded` state and a direct output file URL.

**Step 4 — Status string correction.** The first live end-to-end run revealed that the v2 API returns plain English status strings (`Pending`, `Executing`, `Succeeded`) rather than the prefixed ArcGIS GP style strings (`esriJobExecuting`, `esriJobSubmitted`) carried over from legacy documentation. The polling function's accepted in-progress set was corrected to match.

---

## Verified Working Parameters

| Parameter | Value |
|---|---|
| Submit endpoint | `POST https://lfps.usgs.gov/api/job/submit` |
| Content-Type | `application/json` |
| Required payload fields | `Layer_List`, `Area_of_Interest`, `Email` |
| Optional payload field | `Output_Projection` (EPSG integer as string) |
| Area of Interest format | Space-separated `W S E N` in WGS84 decimal degrees |
| Layer List delimiter | Semicolon |
| Status endpoint | `GET https://lfps.usgs.gov/api/job/status` |
| Status query parameter | `JobId` |
| In-progress status strings | `Pending`, `Executing`, `Submitted`, `Waiting` |
| Completion status string | `Succeeded` |
| Output field on completion | `outputFile` (direct zip download URL) |

---

## Output Projection Fix

Without an explicit `Output_Projection` parameter, LFPS returns a custom Albers Conical Equal Area projection generated per request, centered on the submitted AOI's bounding box coordinates. This produces a different CRS definition on every pull, making any pipeline that assumes a consistent coordinate reference system fail silently on the second run.

Setting `Output_Projection` to `5070` forces all output to NAD83 / Conus Albers (EPSG:5070), the standard LANDFIRE native projection. This was confirmed by inspecting the WKT projection string of the downloaded raster directly via GDAL, which returned a clean EPSG:5070 definition with fixed standard parallels (29.5, 45.5), central meridian (-96), and latitude of origin (23) rather than AOI-centered parameters.

---

## Confirmed Current Layer Codes (LF2024)

The layer codes used by this pipeline were confirmed live against the v2 API. Older documentation and third-party packages reference deprecated code formats (`ELEV2020`, `220F40_22`) that are no longer valid.

| Band | Layer Code | Product |
|---|---|---|
| 1 | `LF2020_Elev` | Elevation |
| 2 | `LF2020_SlpD` | Slope Degrees |
| 3 | `LF2020_Asp` | Aspect |
| 4 | `LF2024_FBFM40` | 40 Scott and Burgan Fire Behavior Fuel Models |
| 5 | `LF2024_CC` | Forest Canopy Cover |
| 6 | `LF2024_CH` | Forest Canopy Height |
| 7 | `LF2024_CBH` | Forest Canopy Base Height |
| 8 | `LF2024_CBD` | Forest Canopy Bulk Density |
| 9 | `LF2024_EVT` | Existing Vegetation Type |
| 10 | `LF2024_EVC` | Existing Vegetation Cover |
| 11 | `LF2024_EVH` | Existing Vegetation Height |

---

*Austin Addington Berlin | AECE Omnis LLC | June 2026*
