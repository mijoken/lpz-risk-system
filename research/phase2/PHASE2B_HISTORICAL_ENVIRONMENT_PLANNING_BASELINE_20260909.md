# Phase 2B Historical Environment Planning Baseline — 2026-09-09

## Status

**PASS — temporal and spatial request planning proven; authenticated ERA5 data retrieval not yet executed.**

## Positive-anchor workload

The official JMA positive registry currently contains **851 realized-positive anchors**. Each anchor has six frozen precursor snapshots:

- T-180
- T-120
- T-90
- T-60
- T-30
- T0

This produces **5,106 requested snapshot mappings**.

## Temporal alignment gate

ERA5 pressure-level data are hourly. Historical snapshots are therefore aligned with the conservative rule:

> Use the latest ERA5 whole-hour analysis time that is **not later than** the requested snapshot time.

No nearest-hour rounding is allowed because it could introduce a future source time into T-minus precursor features.

Live CI evidence from Run 81:

- snapshot mappings: **5,106**
- unique ERA5 source times after de-duplication: **261**
- UTC request days: **45**
- maximum source lag: **50 minutes**
- future ERA5 source times used: **0**

## Official JMA spatial geometry gate

JMA official GIS for primary forecast subdivisions was downloaded and audited in the dedicated historical-spatial workflow.

Spatial Proof Run 2 succeeded after a real-source encoding issue was found and fixed. The official archive was UTF-8 DBF rather than the initially attempted CP932 interpretation.

Results:

- source archive size: **105,851,810 bytes**
- unique primary-subdivision codes appearing in positive anchors: **58**
- resolved from official JMA GIS: **58 / 58**
- unresolved codes: **0**
- official code field detected: `code`

The large source GIS archive is not committed. Only the compact derived bbox registry and provenance are stored in GitHub:

- `research/phase2/primary_subdivision_geometry_registry_20260909.json`

## ERA5 spatial request unit

A single daily Japan-wide union bbox is deliberately not used. Distant events on the same UTC date would create wasteful requests.

Frozen request unit:

**UTC date × JMA primary-subdivision code**

Run 81 result:

- date/subdivision requests: **104**
- unique subdivisions: **58**
- mean ERA5 times per request: **5.0096**
- maximum ERA5 times per request: **14**

Each official subdivision bbox receives a **0.5° retrieval padding** (two ERA5 0.25° grid cells) for environmental context. The padded bbox is only a download envelope and is not treated as the polygon itself.

## Variables planned

Pressure levels:

- 1000 hPa
- 925 hPa
- 850 hPa
- 700 hPa
- 600 hPa
- 500 hPa

Variables:

- relative humidity
- specific humidity
- u wind
- v wind

Initial historical scientific targets:

- RH500 / RH700
- 600-hPa wind orientation environment
- 850-hPa inflow environment
- low-level moisture context

All ERA5-derived features must retain `source = ERA5` and `exactness = PROXY_REANALYSIS`; they are never silently relabeled as live-GFS values.

## Authentication gate

Copernicus programmatic ERA5 retrieval requires a CDS API key. Ordinary CI remains dry-run only.

Current gate:

`authenticated_download_gate = BLOCKED_PENDING_CDS_CREDENTIAL`

No credential is stored in source code or repository files.

## Historical rainfall screening engine

A source-agnostic 1-km analyzed-rainfall screening engine has also been implemented and unit-tested. Once audited historical JMA 1-hour analyzed-rainfall grids are supplied, it can derive 3-hour accumulation and descriptive threshold areas without assigning a negative label.

Current outputs include:

- maximum 3-h accumulation
- mean / p90 / p95 / p99 accumulation
- area at or above 80 / 100 / 150 mm
- whether threshold area reaches 500 km²

The following remain explicitly null:

- `hard_negative_label`
- `lpz_classification`
- `risk_score`

## Gates

```text
JMA positive registry                         PASS
T-180 ... T0 snapshot schedule                PASS
ERA5 no-future-time alignment                 PASS
JMA official primary-subdivision GIS          PASS
58/58 required subdivision bboxes             PASS
ERA5 spatial request manifest                 PASS
ERA5 authenticated retrieval                  BLOCKED_PENDING_CDS_CREDENTIAL
ERA5 historical field decode                  NOT YET PROVEN
historical analyzed-rainfall calculations     UNIT TESTED
historical analyzed-rainfall source payload   NOT YET ACQUIRED
hard-negative registry                        NOT BUILT
risk engine                                    NOT ALLOWED
```
