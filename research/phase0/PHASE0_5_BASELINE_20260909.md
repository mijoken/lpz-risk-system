# Phase 0.5 Baseline — 2026-09-09

## Decision

**Mandatory acquisition payload gate: PASS (4 / 4).**

This is a one-run payload proof, not yet an operational reliability certification. The 30-minute scheduled probe remains in place to accumulate repeated-run evidence before any move to a 5-minute cadence.

## GitHub Actions evidence

Workflow run: `34324248667`

Head commit: `1c60420253cd1c01133a5b80a5939d2b5b2d1134`

Artifact: `phase0-5-acquisition-report-34324248667`

Artifact digest: `sha256:3eea543601a9603ad378b36e62ab335bf91f7d8e5bdec65b84847a022f8ceed5`

Generated at: `2026-09-09T07:31:10.905912Z`

## Results

| Source | Role | Evidence | Status | Data time (UTC) | Data age | Payload size | Latency |
|---|---|---|---|---|---:|---:|---:|
| JMA High-Resolution Precipitation Nowcast | mandatory | PNG tile | PASS | 07:25 | 368 s | 8,067 B | 113 ms |
| JMA analyzed precipitation (RASRF) | mandatory | PNG tile | PASS | 07:20 | 669 s | 6,985 B | 950 ms |
| JMA AMeDAS | mandatory | JSON map | PASS | 07:20 | 670 s | 251,853 B | 256 ms |
| NOAA/NCEP GFS 0.25° | mandatory | GRIB2 subset | PASS | 00:00 cycle | 27,070 s | 25,801 B | 193 ms |
| JMA WINDAS | supplementary | endpoint discovery | PENDING | — | — | — | — |
| JMA Himawari | supplementary | metadata | META_PASS | 07:20 | 670 s | 14,419 B | 466 ms |

## Important observations

### 1. All mandatory sources reached real payload proof

The mandatory Phase 0.5 gate is satisfied at the transport/parse level. This means GitHub Actions can obtain actual scientific payloads rather than merely reaching documentation or metadata endpoints.

### 2. Himawari ordering defect discovered and fixed

The first probe assumed the first metadata row was current. `targetTimes_fd.json` was observed with older rows before newer rows, which produced a false stale reading. The acquisition code now selects the maximum `validtime` / `basetime` and a regression test prevents reintroduction of this defect.

### 3. GFS cycle fallback was exercised in real operation

At approximately 07:31 UTC the 06 UTC `f000` sample returned HTTP 404, while the preceding 00 UTC cycle returned a valid GRIB2 payload. The probe therefore proved that a live system must distinguish "new cycle not available yet" from a source outage and fall back to a completed prior cycle.

This behavior is acceptable for the environmental-background role of GFS, but the eventual feature adapter must record both cycle age and forecast valid time.

### 4. PASS does not yet mean operationally reliable

A single successful run cannot establish availability. Before increasing the schedule to five minutes, repeated runs must quantify:

- payload success rate
- metadata success rate
- data-age distribution
- download latency distribution
- cycle fallback frequency
- consecutive failure behavior
- upstream format drift

## Next engineering gate

Build the **Canonical Data Adapter layer** before any LPZ risk score.

Target canonical families:

1. `radar_frame` — Nowcast / RASRF spatial raster metadata and later decoded precipitation field.
2. `surface_station_frame` — AMeDAS observations with normalized wind components.
3. `environment_frame` — GFS environmental variables and pressure-level fields.
4. `source_health` — freshness, latency, payload validity and source state.

Supplementary Himawari and WINDAS adapters can be added without blocking the mandatory core.

## Freeze rule

No LPZ predictor weights, thresholds, or risk score should be introduced until the canonical mandatory data frames can be generated reproducibly from both local execution and GitHub Actions.
