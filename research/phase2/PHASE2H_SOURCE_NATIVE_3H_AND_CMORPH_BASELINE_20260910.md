# Phase 2H — Source-Native 3-Hour Rainfall, Official Polygon Masking, and CMORPH Baseline

Date: 2026-09-10 JST
Repository: `mijoken/lpz-risk-system`
Risk engine: OFF
Candidate heavy-rain threshold: NOT SELECTED
Hard-negative labels: OFF

## Decision

Phase 2H establishes the mechanics required to reconstruct historical three-hour precipitation without temporal resampling, cross-source averaging, or future-interval leakage. It also completes real-payload proof for the third free historical precipitation source, NOAA/NCEI CMORPH CDR.

The three free historical precipitation roles remain:

1. JAXA GSMaP Gauge Standard v8 — primary historical free source
2. NASA IMERG Final V07 — independent historical secondary source
3. NOAA/NCEI CMORPH CDR v1.0 — tertiary independent backup/diagnostic source

None is treated as a JMA 1-km analyzed-rainfall/radar equivalent. JMA 1-km objective thresholds are not copied directly onto these satellite grids.

## Exact source-native three-hour semantics

Implemented in `src/lpz_risk/historical_rainfall_window.py`.

A three-hour field is accepted only when:

- one provider is used throughout the window,
- one product version is used throughout the window,
- native validity intervals are exactly consecutive,
- total native duration is exactly 10,800 seconds,
- longitude/latitude grids are unchanged within the window,
- no interpolation or temporal resampling is performed.

Therefore:

- GSMaP: 3 × 1-hour native fields
- IMERG: 6 × 30-minute native fields
- CMORPH: 6 × 30-minute native fields

Cross-source and cross-version accumulation are hard errors.

## Official primary-subdivision polygon masking

The already-frozen Phase 2C official JMA primary-subdivision geometry is reused. Final membership semantics remain:

`GRID_CELL_CENTRE_INSIDE_OFFICIAL_POLYGON`

A computational optimization was added after the initial real pilot exposed an avoidable cost: the official polygon bounding box first restricts the candidate grid, then the exact point-in-polygon test is applied only to that subset. The bounding box is only a prefilter and does not change polygon membership semantics.

This reduced a global multi-million-cell point-in-polygon pass to the small local grid surrounding the official polygon while retaining the frozen scientific rule.

## Real three-hour accumulation + polygon proof

Workflow: `LPZ Historical Rainfall 3H Polygon Pilot`
Successful Run ID: `34411159348`
Artifact ID: `10127294372`
Split: `DEVELOPMENT`
Window: `2023-01-01T00:00:00Z` to `2023-01-01T03:00:00Z`
Primary subdivision code: `390030`
Gate: `PASS_REAL_3H_ACCUMULATION_AND_OFFICIAL_POLYGON_MASKING`

### GSMaP

- product: v8.0000.0
- native fields: 3
- accumulated duration: 10,800 s
- global grid: 1200 × 3600
- global three-hour maximum in this proof: 228.65752410888672 mm
- official-polygon bbox prefilter: 8 × 8 cells
- final polygon cells: 30
- finite polygon cells: 30
- finite coverage: 1.0
- polygon finite area: 3105.0923145953125 km²
- polygon max/mean/p90/p95/p99: all 0.0 mm for this proof window

### IMERG Final V07

- product: 07
- native fields: 6
- accumulated duration: 10,800 s
- global grid: 1800 × 3600
- finite global cells in accumulated field: 6,440,651
- missing global cells: 39,349
- global three-hour maximum in this proof: 133.9899959564209 mm
- official-polygon bbox prefilter: 8 × 8 cells
- final polygon cells: 30
- finite polygon cells: 30
- finite coverage: 1.0
- polygon finite area: 3105.119848504244 km²
- polygon max/mean/p90/p95/p99: all 0.0 mm for this proof window

The zero-rain polygon result is not used to choose or reject any heavy-rain threshold. This run proves mechanics only.

Source comparison semantics are `SIDE_BY_SIDE_ONLY_NO_AVERAGING`.

## NOAA/NCEI CMORPH CDR real-payload proof

Workflow: `LPZ CMORPH CDR Payload Proof`
Run ID: `34410535943`
Artifact ID: `10127050320`
Gate: `PASS_REAL_CMORPH_CDR_CANONICAL_DECODE`

Real file:

`CMORPH_V1.0_ADJ_8km-30min_2023010100.nc`

Observed proof properties:

- payload bytes: 1,559,390
- native half-hour fields: 2 per hourly file
- canonical grid shape: 1649 × 4948
- native interval: 1,800 s
- first field maximum: 57.03999710083008 mm/hr
- second field maximum: 59.709999084472656 mm/hr
- Japan bbox first-field shape: 220 × 234
- Japan bbox finite cells: 51,477
- Japan bbox missing cells: 3
- Japan bbox max: 2.97 mm/hr
- Japan bbox mean: 0.0084608658 mm/hr

Raw NetCDF was not persisted.

## DEVELOPMENT-only request-window manifest

Implemented in `src/lpz_risk/rainfall_window_manifest.py` and proven through the existing positive-episode workflow.

Workflow Run ID: `34411031036`
Artifact ID: `10127233393`
Conclusion: SUCCESS

Frozen DEVELOPMENT population:

- 501 realized-positive anchors
- 65 conservative same-subdivision local episodes
- 3 providers
- 1,503 anchor-provider mappings
- 567 unique provider/subdivision/three-hour request windows after de-duplication
- future interval count: 0

By provider:

- GSMaP: 501 anchor mappings → 137 unique 3-hour windows; max source lag 3,000 s
- IMERG: 501 anchor mappings → 215 unique 3-hour windows; max source lag 1,200 s
- CMORPH: 501 anchor mappings → 215 unique 3-hour windows; max source lag 1,200 s

Window-end policy is:

`LATEST_COMPLETED_NATIVE_INTERVAL_BOUNDARY_AT_OR_BEFORE_ANCHOR`

Thus no future rainfall interval is used. The lag is recorded explicitly instead of being hidden by interpolation.

## Calibration guardrail

`src/lpz_risk/rainfall_calibration.py` now provides DEVELOPMENT-only descriptive distribution summaries for max/mean/p90/p95/p99 three-hour rainfall. It hard-fails if any Validation, retrospective-test, or prospective-holdout row reaches calibration.

Current calibration status:

`NOT_SELECTED_DESCRIPTIVE_DISTRIBUTION_ONLY`

No candidate threshold has been selected from the single pilot or from Validation data.

## Gates after Phase 2H

- GSMaP real payload: PASS
- GSMaP canonical decode: PASS
- IMERG real payload: PASS
- IMERG canonical decode: PASS
- CMORPH real payload: PASS
- CMORPH canonical decode: PASS
- exact source-native 3-hour accumulation: PASS_REAL_PILOT
- official JMA polygon masking: PASS_REAL_PILOT
- bbox computational prefilter: PASS / membership semantics unchanged
- DEVELOPMENT rainfall request manifest: PASS
- future interval leakage: 0
- temporal resampling: DISABLED
- cross-source accumulation/averaging: DISABLED
- candidate heavy-rain threshold: NOT SELECTED
- hard-negative registry: NOT BUILT
- risk engine: OFF

## Next stage

The next stage is a controlled DEVELOPMENT reconstruction across the frozen 567 unique request windows, producing one source-native three-hour official-polygon descriptor per available request. Raw satellite payloads remain ephemeral. Derived descriptors and completion/error provenance are retained.

Only after the DEVELOPMENT descriptor population exists may empirical rainfall distributions be inspected to propose candidate heavy-rain screening thresholds. Those candidates must then be frozen before any 2025 Validation evaluation. The 2026 retrospective set and prospective holdout remain excluded from threshold selection.
