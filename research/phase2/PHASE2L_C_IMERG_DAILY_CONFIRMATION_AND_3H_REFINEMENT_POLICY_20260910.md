# Phase 2L-C IMERG Daily Confirmation and 3h Refinement Policy — 2026-09-10

## Completed daily confirmation
Development-only CMORPH candidate reservoir was independently re-measured with NASA IMERG Final V07 daily data.

- Full workflow Run: `34471420254`
- Final artifact: `phase2l-imerg-independent-confirmation-full-34471420254`
- Artifact ID: `10153889627`
- Candidate region-days: 5,943 / 5,943 confirmed
- Unique UTC days: 449 / 449 confirmed
- Candidate membership changed by IMERG: NO
- Source fusion: NO

Descriptive CMORPH vs IMERG agreement over the 5,943 already-selected region-days:

| Spatial statistic | Pearson | Spearman | Mean IMERG-CMORPH (mm/day) | Median absolute difference (mm/day) |
|---|---:|---:|---:|---:|
| mean | 0.9406 | 0.9280 | -2.454 | 3.393 |
| max | 0.8533 | 0.7910 | +2.933 | 10.965 |
| p90 | 0.9045 | 0.8740 | -3.856 | 6.611 |
| p95 | 0.8928 | 0.8490 | -3.763 | 7.614 |

Interpretation: source agreement is high for broad spatial rainfall intensity and weakens toward local extrema, consistent with the earlier positive-episode dual-source result. IMERG is confirmation only and did not modify the CMORPH-selected candidate set.

## Exact 3-hour refinement policy
Daily UTC bins are screening units only and are not event windows. The next stage returns to source-native sub-daily data.

For IMERG Final V07 half-hourly precipitation:

- temporal resolution: 30 minutes;
- one exact 3-hour window = six consecutive native half-hour slots;
- for each CMORPH-selected candidate UTC day, evaluate every 3-hour window whose **start time** lies from previous-day 21:30 UTC through candidate-day 23:30 UTC inclusive;
- therefore boundary-crossing windows on both sides of the candidate UTC day are retained;
- no interpolation across missing slots is allowed;
- a window is valid only when all six required native slots are present and decodable;
- calculate cellwise 3-hour accumulation first, then source-native matched-window spatial summaries (`mean`, `max`, `p90`, `p95`);
- retain the maximizing window start/end timestamp for each spatial summary rather than only the magnitude;
- do not average or fuse IMERG with CMORPH;
- do not use ERA5/environment variables to choose the rainfall window;
- do not assign non-LPZ or Hard Negative labels in this stage.

Adjacent candidate UTC days may produce the same physical heavy-rain event. Such duplicates are intentionally retained here and will be grouped only in a later event/episode construction stage.

## Guardrails
- Development 2023-2024 only.
- Validation 2025 untouched.
- Retrospective 2026 untouched.
- Prospective holdout untouched.
- Hard Negative OFF.
- Environment-variable selection OFF.
- Source fusion OFF.
- GSMaP discovery OFF.
- Risk Engine OFF.

## Next gate
Run a small fixed-date IMERG half-hourly rolling-3h pilot. The pilot tests access, granule completeness, time decoding, six-slot continuity, boundary handling, and matched-window spatial aggregation. It is not used to tune rainfall thresholds or candidate membership.
