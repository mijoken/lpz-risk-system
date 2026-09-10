# Phase 2L GSMaP Access and Confirmatory Role Baseline — 2026-09-10

## Status

GSMaP Standard v8 historical access has recovered sufficiently for controlled automated research use, but the cause of the earlier FTP authentication failures remains unknown. This baseline does not declare the provider-side issue resolved.

Frozen access status:

`ACCESS_RECOVERED_AUTOMATED_24H_SEQUENTIAL_TRANSFER_CONFIRMED_CAUSE_UNKNOWN`

## Provider documentation supplied by the user

JAXA `README.first.txt` states that Standard v8 archives GSMaP_MVK and GSMaP_Gauge since 1998-01-01, defines hourly NetCDF under `/standard/v8/netcdf/YYYY/MM/DD/`, and defines daily gauge-calibrated products under `/standard/v8/daily_G/...`.

JAXA `GSMaP_MVK_RNL_HISTORY.txt` states that Algorithm Version 8 began in December 2021, historical January 1998–November 2021 data were reprocessed and uploaded in July 2023, and NetCDF products after December 2021 were released in June 2024.

The supplied real NetCDF sample and GitHub Actions proofs confirm that the NetCDF representation contains at least `hourlyPrecipRate`, `hourlyPrecipRateGC`, and `reliabilityFlag`.

## Automated access proofs

### Single-file proof

- Workflow run: `34432971833`
- Gate: `PASS_GSMAP_V8_NETCDF_SINGLE_FILE_FTP_PROOF`
- Remote file: `/standard/v8/netcdf/2023/07/10/gsmap_mvk.20230710.0000.v8.0000.0.nc`
- Payload bytes: `6,109,989`
- Parallel connections: 1
- Broad traversal: disabled
- Raw payload persistence: disabled

### 24-hour sequential proof

- Workflow run: `34433061304`
- Gate: `PASS_GSMAP_V8_NETCDF_24H_SEQUENTIAL_FTP_PROOF`
- Date: `2023-07-10`
- Completed files: `24 / 24`
- Total payload bytes: `154,131,338`
- Transfer/proof elapsed time: `98.202 s`
- One FTP control session
- Parallel connections: 1
- Automatic reconnect: disabled
- Per-file retry count: 0
- Pause between transfers: 1 second
- No provider error was observed at this load.

These proofs establish feasibility, not an authorized provider rate limit. No claim is made that higher concurrency or larger sustained retrievals are permitted or safe.

## Phase 2L source-role decision

For Heavy-Rain Candidate Population Discovery, GSMaP will **not** be used to bulk-screen every Development day at this stage.

The frozen two-stage role is:

1. **Discovery population:** IMERG Final V07 daily + CMORPH CDR daily over Development 2023–2024.
2. **Candidate refinement:** source-native higher-time-resolution rainfall reconstruction for candidate region-days/windows.
3. **Independent confirmatory source:** GSMaP Standard v8, preferentially NetCDF `hourlyPrecipRateGC`, retrieved only for the reduced candidate windows/days and the frozen realized-positive reference episodes.
4. Preserve GSMaP `hourlyPrecipRate`, `hourlyPrecipRateGC`, and `reliabilityFlag` separately. Do not fuse rainfall products into one synthetic truth.

Rationale:

- avoids unnecessary high-volume FTP load while provider-side failure cause is unresolved;
- avoids using all three products to define the candidate set and then calling three-product agreement an independent confirmation;
- keeps GSMaP as a partially out-of-selection confirmatory coordinate;
- still permits three-source robustness checks for the scientifically important heavy-rain vs LPZ comparison.

## Research guardrails

- Development only: 2023–2024.
- Validation 2025: untouched.
- Retrospective 2026: untouched.
- Prospective holdout: untouched.
- Heavy-rain threshold selection: OFF at this baseline.
- Hard-negative labeling: OFF.
- Source fusion: OFF.
- GSMaP provider rate-limit assumptions: NONE.
- Risk Engine: OFF.

## Next gate

Proceed to Phase 2L-A: Development 2023–2024 Daily Rainfall Census using IMERG and CMORPH as the discovery population. The census must characterize source-native distributions before selecting any screening threshold. GSMaP enters only after candidate reduction as an independent confirmatory rainfall source.
