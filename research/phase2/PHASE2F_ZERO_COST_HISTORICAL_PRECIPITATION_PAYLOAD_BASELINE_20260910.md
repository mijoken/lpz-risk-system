# Phase 2F — Zero-Cost Historical Precipitation Payload Baseline

Date: 2026-09-10 JST
Repository: `mijoken/lpz-risk-system`
Policy: `ZERO_COST_EXTERNAL_DATA_REQUIRED`
Risk engine: OFF

## Decision

The historical precipitation stack is now anchored to free sources only. Paid JMA historical media is not a required dependency. DIAS/XRAIN remains optional and may not block the core system.

Primary / secondary roles are frozen as:

1. JAXA GSMaP Gauge Standard v8 — PRIMARY_HISTORICAL_FREE
2. NASA IMERG Final V07 — INDEPENDENT_HISTORICAL_SECONDARY_FREE
3. NOAA CMORPH CDR — TERTIARY_HISTORICAL_BACKUP_FREE
4. ERA5-Land total precipitation — QUATERNARY_REANALYSIS_BACKUP_FREE
5. JMA public radar derived features — PROSPECTIVE_NATIVE_FREE

No source is allowed to silently replace another. Primary/backup disagreement must be retained as a data-quality diagnostic. Satellite products must not be treated as 1 km radar equivalents and JMA 1 km thresholds must not be copied directly onto coarse satellite grids.

## GSMaP authenticated and real-file proof

Workflow: `LPZ GSMaP Standard v8 Payload Proof`
Preferred efficient proof run ID: `34408806066`
Artifact ID: `10126411800`
Conclusion: SUCCESS
Discovery method: `MLSD_WITH_CONSERVATIVE_NLST_FALLBACK`

The earlier initial proof run `34407808498` also succeeded, but used inefficient per-entry directory probing. The preferred run above closes that engineering issue and discovers the 2023 payload hierarchy efficiently.

Authenticated FTP host: `hokusai.eorc.jaxa.jp`
Official product root: `/standard/v8`
Official gauge-calibrated hourly hierarchy confirmed from live FTP and JAXA README:

`/standard/v8/hourly_G/YYYY/MM/DD/`

The live 2023 tree was confirmed through year → month → day, with 24 hourly Gauge files on 2023-01-01.

A real 2023 GSMaP Gauge Standard v8 payload was acquired ephemerally:

`/standard/v8/hourly_G/2023/01/01/gsmap_gauge.20230101.0000.v8.0000.0.dat.gz`

Payload bytes: `2,321,026`
SHA-256 prefix: `49dd4de502785b94`

The official README retrieved from the authenticated FTP also confirmed:

- archive from 1998-01-01
- GSMaP_MVK and GSMaP_Gauge
- hourly Gauge-calibrated Rain Rate file naming
- official format document path `/standard/v8/doc/DataFormatDescription_MVK_RNL_v8.0000.pdf`
- NetCDF/HDF product locations
- daily/monthly product locations

Current scientific gate:

`PASS_REAL_FILE_ACQUIRED_FORMAT_DECODE_PENDING`

The raw `.dat.gz` was not committed or persisted. Decoder semantics will be implemented only after the official JAXA format document is audited; no guessed binary interpretation is allowed.

## NASA Earthdata / IMERG authenticated and real-HDF5 proof

Initial Earthdata authentication and CMR search succeeded, but the first payload attempt was blocked by GES DISC EULA acceptance. The user then explicitly accepted the required GES DISC EULA.

Workflow: `LPZ Free Precipitation Payload Proof`
Run ID: `34407619673`
Run attempt: `2`
Artifact ID: `10126333220`
Conclusion: SUCCESS

Collection:

- short name: `GPM_3IMERGHH`
- version: `07`
- Final Run 30-minute product

Real payload acquired and decoded:

`3B-HHR.MS.MRG.3IMERG.20250701-S000000-E002959.0000.V07B.HDF5`

Payload bytes: `8,039,089`
Dataset count: `19`
Precipitation-related datasets: `7`

Canonical precipitation dataset identified:

`/Grid/precipitation`

Properties observed in the real payload:

- dtype: float32
- shape: `[1, 3600, 1800]`
- units: `mm/hr`
- semantics: Complete merged microwave-infrared, gauge-adjusted precipitation estimate

Finite-value descriptor from the proof granule:

- finite count: `6,455,517`
- minimum: `0.0 mm/hr`
- maximum: `57.21999740600586 mm/hr`
- mean: `0.10063915331338963 mm/hr`

Current scientific gate:

`PASS_REAL_HDF5_ACQUIRED_AND_DECODED`

The raw HDF5 was not committed or persisted.

## Security and scientific guardrails

All authentication secrets are supplied through GitHub Actions repository secrets. Secret values are never written to reports or artifacts.

The proof reports enforce:

- `secret_value_recorded = false`
- `raw_payloads_persisted = false`
- `lpz_classification = null`
- `risk_score = null`
- `risk_engine_allowed = false`

## What this baseline establishes

The zero-cost historical precipitation strategy is no longer a paper design. Both the primary source (GSMaP) and independent secondary source (IMERG) have passed authenticated live access. GSMaP has passed real 2023 file acquisition. IMERG has passed real HDF5 acquisition and scientific dataset inspection.

This is sufficient to proceed to the next engineering stage: a common Canonical Historical Rainfall Schema, source-native accumulation logic, official primary-subdivision polygon masking, and Development-only calibration of severe-rain candidate thresholds.

Hard-negative labels remain disabled until those source-native calibration and leakage controls are complete.
