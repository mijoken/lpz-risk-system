# Phase 2L-C — CMORPH Matched-Window Coverage Baseline

Date: 2026-09-10
Split: Development 2023-2024 only

## Purpose

Determine whether NOAA CMORPH CDR daily 0.25-degree data have sufficient spatial support for coarse, recall-oriented region-day screening around the frozen Development LPZ regions.

This is not final 3-hour rainfall matching and does not define Hard Negatives.

## Failed direct-polygon preflight

Direct official-JMA-polygon masking at 0.25 degrees was rejected as too coarse for many primary subdivisions. In Run 34467020817, among the 45 unique primary subdivisions present in the frozen Phase 2K Development 65-episode set, the direct-polygon cell-count median was 3, 25/45 regions had fewer than 4 cells, 43/45 had fewer than 8, and at least one region had zero cells.

Therefore CMORPH 0.25-degree daily data MUST NOT be used as a direct primary-subdivision polygon severity measure for candidate selection.

## Matched-window definition

The matched screening window is frozen as:

- official JMA primary-subdivision geometry bounding box
- plus 0.5 degrees padding on all sides
- clipped to the Japan research domain

The 0.5-degree padding is not tuned here. It is inherited from the already-frozen ERA5 historical spatial retrieval configuration in `config/historical_environment_era5.json`.

Role: coarse recall-oriented daily screening only.

## Predeclared adequacy gate

Minimum 16 CMORPH grid cells per matched window, approximately 4 x 4 equivalent support, before mean/tail summaries may be used for coarse region-day screening.

## Result

Workflow: `LPZ Phase 2L-C CMORPH Matched Window Coverage Proof`
Run: `34467528651`
Artifact: `10148144581`
Artifact name: `phase2l-cmorph-matched-window-coverage-proof-34467528651`

Gate: `PASS_CMORPH_MATCHED_WINDOW_COVERAGE_MIN16`

Across all 45 frozen Development matched-domain primary subdivisions:

- minimum grid-cell count: 30
- median grid-cell count: 48
- maximum grid-cell count: 160
- regions below 16 cells: 0
- zero-cell regions: 0

## Frozen interpretation

CMORPH daily 0.25-degree is adequate for coarse matched-window screening when used with the frozen primary-subdivision bbox + 0.5-degree padding window.

It is not adequate as a direct official-polygon severity representation for many small/narrow primary subdivisions.

The next step is a complete 2023-2024 Development matched-window spatial census over all 731 days x 45 regions. Candidate rules remain OFF until the census distribution and Positive recall are measured.

## Guardrails

- Threshold selection: OFF
- Candidate generation: OFF
- Hard Negative labeling: OFF
- Source fusion: OFF
- GSMaP discovery use: OFF
- Validation 2025: untouched
- Retrospective 2026: untouched
- Prospective holdout: untouched
- Risk Engine: OFF
