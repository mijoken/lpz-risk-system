# Phase 2G — Canonical Historical Rainfall Adapter Baseline

Date: 2026-09-10 JST
Repository: `mijoken/lpz-risk-system`
Cost policy: `ZERO_COST_EXTERNAL_DATA_REQUIRED`
Risk engine: OFF

## Purpose

Freeze a common source-aware rainfall representation for the free historical precipitation stack without erasing native temporal semantics or averaging providers together.

## JAXA GSMaP Gauge Standard v8 specification audit

Official source: JAXA/EORC `DataFormatDescription_MVK_RNL_v8.0000.pdf`, updated 2024-10-09.

The implementation is based on the documented facts below, not inferred from file size:

- Hourly Gauge-calibrated Rain Rate
- 4-byte float plain binary
- little-endian
- gzip compressed
- 3600 longitude rows × 1200 latitude lines
- 0.1° × 0.1° grid
- global 60°N–60°S
- first cell center: 0.05°E, 59.95°N
- hourly value is mean rain rate from minute 00 through 59 of the named UTC hour
- units: mm/hr
- documented negative missing codes: -4, -8, -99
- Gauge data directory: `/standard/v8/hourly_G/YYYY/MM/DD/`

Implementation: `src/lpz_risk/gsmap_v8.py`

## IMERG Final V07 adapter

Implementation: `src/lpz_risk/imerg_v07.py`

Canonical precipitation dataset:

`/Grid/precipitation`

Observed real V07 array order is `TIME_LON_LAT`; the adapter converts it to canonical `LAT_LON` while preserving the original lon/lat coordinate arrays.

The filename interval `S000000-E002959` is represented canonically as half-open `[00:00:00, 00:30:00)` and therefore has `accumulation_seconds=1800`.

## Canonical field contract

Implementation: `src/lpz_risk/canonical_rainfall.py`

Every field stores:

- source ID and product version
- timezone-aware valid start/end UTC
- exact accumulation interval seconds
- native mean rain rate in mm/hr
- explicit longitude and latitude coordinate arrays
- gauge-adjusted flag
- source path/hash prefix
- source-native quality metadata
- no hard-negative label
- no LPZ classification
- no risk score

Rainfall amount is derived by time integration:

`accumulation_mm = rain_rate_mm_per_hr × accumulation_seconds / 3600`

Therefore one GSMaP hourly field integrates over 3600 seconds, while one IMERG HH field integrates over 1800 seconds.

Consecutive accumulation forbids:

- cross-source mixing
- temporal gaps
- grid-shape mismatches

No cross-source averaging is performed.

## Real-payload canonical proof

Workflow: `LPZ Canonical Rainfall Real Proof`
Run ID: `34409514204`
Successful attempt: 2
Job ID: `102660711720`
Artifact ID: `10126710619`
Conclusion: SUCCESS

Attempt 1 was interrupted by a transient GitHub-hosted-runner network error to `urs.earthdata.nasa.gov`; the same job was rerun without code or credential changes and succeeded.

### GSMaP real field

Payload:
`gsmap_gauge.20230101.0000.v8.0000.0.dat.gz`

- product version: `v8.0000.0`
- valid interval: 2023-01-01 00:00–01:00 UTC
- accumulation seconds: 3600
- canonical shape: 1200 × 3600
- finite cells: 4,320,000
- missing cells in this field: 0
- global min/max rain rate: 0 / 77.2481918334961 mm/hr
- source hash prefix: `49dd4de502785b94`
- gate: `PASS_REAL_GSMAP_CANONICAL_DECODE`

Japan bbox [129E,30N,146E,46N]:

- shape: 160 × 170
- cells: 27,200
- finite: 27,200
- min/max: 0 / 3.819999933242798 mm/hr
- mean: 0.028107477306021953 mm/hr

### IMERG real field

Payload:
`3B-HHR.MS.MRG.3IMERG.20250701-S000000-E002959.0000.V07B.HDF5`

- product version: 07
- valid interval: 2025-07-01 00:00–00:30 UTC
- accumulation seconds: 1800
- canonical shape: 1800 × 3600
- finite cells: 6,455,517
- missing cells: 24,483
- global min/max rain rate: 0 / 57.21999740600586 mm/hr
- source hash prefix: `df74bbd291f738a0`
- gate: `PASS_REAL_IMERG_CANONICAL_DECODE`

Japan bbox [129E,30N,146E,46N]:

- shape: 160 × 170
- cells: 27,200
- finite: 27,200
- min/max: 0 / 18.600000381469727 mm/hr
- mean: 0.09617683620959082 mm/hr

## Automated tests

`tests/test_canonical_rainfall.py` verifies:

- hourly vs half-hour interval integration
- exact temporal continuity
- cross-source mixing is rejected
- official GSMaP full 4,320,000-cell geometry
- little-endian float decoding
- official missing-value conversion
- IMERG lon/lat transpose
- IMERG half-hour integration

Normal scientific CI run `34409432240` concluded SUCCESS with these tests.

## Gate

```text
GSMaP official format audit       PASS
GSMaP real canonical decode       PASS
IMERG real canonical decode       PASS
Canonical interval integration    PASS
Cross-source mixing guardrail     PASS
Raw persistence                   OFF
Hard-negative labeling            OFF
Risk engine                       OFF
```

Next stage: source-native 3-hour accumulation over historical windows, primary-subdivision polygon masking, and DEVELOPMENT-only severe-rain calibration. NOAA CMORPH remains a tertiary independent backup and still requires its own real-payload proof.
