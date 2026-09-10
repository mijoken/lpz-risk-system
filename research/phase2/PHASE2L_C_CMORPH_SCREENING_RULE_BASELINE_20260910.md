# Phase 2L-C CMORPH High-Recall Screening Rule Baseline — 2026-09-10

## Purpose
Freeze a broad Development-only rainfall screening rule before non-LPZ candidate generation. The rule is a rainfall-severity reservoir rule, not an LPZ classifier and not a Hard Negative label.

## Source population
- Split: Development only, 2023-01-01 through 2024-12-31 UTC.
- Spatial domain: 45 JMA primary subdivisions represented in the frozen Phase 2K Development 65 episodes.
- Screening window: official JMA primary-subdivision geometry bounding box plus the already-frozen ERA5 0.5 degree padding.
- Rainfall source: NOAA CMORPH CDR daily 0.25 degree.
- Complete census: 731 days x 45 regions = 32,895 region-days, Run 34467829960.

## Coverage prerequisite
The direct polygon-centre mask was rejected because the 0.25 degree grid was too sparse at subdivision scale. The fixed 0.5 degree matched-window proof passed for all 45 regions with minimum 30, median 48 and maximum 160 CMORPH cells (Run 34467528651). The 0.5 degree value was inherited from the frozen ERA5 retrieval design and was not tuned here.

## Positive-position evidence
For the 65 frozen Development positive episodes under direct UTC-date mapping, the same-region 731-day percentile distributions were strongly upper-tailed. Minimum observed percentiles were approximately 86.59 for window maximum, 83.17 for p90, and 83.99 for p95; medians were approximately 99.18, 99.32, and 99.32 respectively. Calendar-month ranks were retained descriptively but are not used for screening because direct UTC-day bins are not event windows and because the reservoir must remain broad.

## Frozen screening rule
Rule ID: `CMORPH_REGION_ANNUAL_P80_INTERSECTION_MAX_P90_P95_V1`

A Development region-day enters the broad candidate reservoir only when all three source-native CMORPH daily metrics are at or above the 80th percentile of that same primary subdivision across all 731 Development days:

1. matched-window daily maximum >= same-region P80;
2. matched-window daily p90 >= same-region P80;
3. matched-window daily p95 >= same-region P80.

The percentile is a rounded high-recall threshold. No negative labels, ERA5 variables, IMERG values, GSMaP values, Validation 2025 data, 2026 retrospective data, or prospective holdout data are used to select it.

## Interpretation
Passing this rule means only: "a comparatively strong, spatially substantial rain day for this region that deserves finer independent rainfall review." It does not mean LPZ, non-LPZ, Hard Negative, forecast signal, or risk score.

## UTC boundary rule
CMORPH daily bins are UTC calendar days. Direct mapping of a Positive analysis time to its UTC date is used only for a descriptive recall audit. Final rainfall matching must return to sub-daily source-native data and evaluate exact consecutive 3-hour windows, including windows that cross UTC day boundaries. Daily bins must never be treated as event windows.

## Next step
Generate the Development candidate reservoir under the frozen rule, then use IMERG as an independent finer-resolution rainfall confirmation source only for the retained region-days. GSMaP remains outside discovery and reserved for later confirmatory comparison.

## Guardrails
- Hard Negative label: OFF.
- Environment-variable selection: OFF.
- Source fusion: OFF.
- IMERG selection: OFF at this stage.
- GSMaP discovery: OFF.
- Validation 2025: untouched.
- Retrospective 2026: untouched.
- Prospective holdout: untouched.
- Risk Engine: OFF.
