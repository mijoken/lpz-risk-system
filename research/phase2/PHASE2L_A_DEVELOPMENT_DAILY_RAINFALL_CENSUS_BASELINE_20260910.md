# Phase 2L-A — Development Daily Rainfall Census Baseline

Date: 2026-09-10
Status: **FROZEN DESCRIPTIVE DEVELOPMENT BASELINE**

## Purpose

Establish the complete 2023–2024 Development daily rainfall population before defining any heavy-rain candidate threshold or Hard Negative label. This phase asks where the frozen realized-positive LPZ episodes sit within the broader rainfall-day distribution. It does **not** create negatives and does **not** select a rainfall cutoff.

## Source and split policy

- Development only: 2023-01-01 through 2024-12-31 UTC, 731 days.
- Discovery rainfall sources remain independent and source-native:
  - NASA IMERG Final V07 daily (`GPM_3IMERGDF`)
  - NOAA CMORPH CDR daily 0.25 deg
- GSMaP is **not used for discovery**; it remains confirmatory for later candidate-level reconstruction.
- Summary envelope: 122E–150E, 24N–47N.
- This envelope is a coarse Japan-domain retrieval/summary box. It is **not** a Japan land mask and **not** a JMA primary-subdivision polygon.
- Daily products are for population screening/context only. Final LPZ-vs-non-LPZ comparisons must return to high-time-resolution, source-native 3-hour rainfall reconstruction.

## Execution provenance

Initial monthly census workflow:

- Run: `34433650943`
- Result: partial failure caused by transient Earthdata network reachability faults during login, not by scientific decoding or missing rainfall data.
- Successful original monthly artifacts were retained and reused.

Observed failed months in the first pass:

- 2023-07
- 2023-09
- 2023-11
- 2023-12
- 2024-03
- 2024-11

The inspected failures were `OSError: [Errno 101] Network is unreachable` while reaching `urs.earthdata.nasa.gov`, before rainfall processing. The monthly script was hardened with a five-attempt Earthdata-login backoff policy.

Recovery and final merge:

- Run: `34434303567`
- Recovery: **6/6 missing months PASS**
- Final merge: **PASS**
- Final artifact: `phase2l-development-daily-rainfall-census-final-34434303567`
- Artifact ID: `10135715763`
- Final gate: `PASS_COMPLETE_DEVELOPMENT_DAILY_RAINFALL_CENSUS`

Completeness:

- Development days: **731 / 731**
- Source-day rows: **1,462 / 1,462**
- IMERG: **731 / 731**
- CMORPH: **731 / 731**
- Frozen Development positive episodes: **65 / 65**
- Unique UTC dates represented by those 65 local episodes: **22**

## Daily Japan-domain distributions

These are source-native daily grid summaries over the broad retrieval envelope. They must not be interpreted as JMA-subdivision rainfall.

### IMERG Final V07

| Daily grid summary | Median | P90 day | P95 day | P99 day | Max day |
|---|---:|---:|---:|---:|---:|
| Domain mean | 3.828 | 8.215 | 9.602 | 12.734 | 14.527 |
| Grid p90 | 11.440 | 25.686 | 31.440 | 41.995 | 53.420 |
| Grid p95 | 20.780 | 42.941 | 50.008 | 70.641 | 87.058 |
| Grid p99 | 45.155 | 92.660 | 109.395 | 162.260 | 207.230 |
| Grid maximum | 111.515 | 257.785 | 317.590 | 428.388 | 624.905 |

### CMORPH CDR

| Daily grid summary | Median | P90 day | P95 day | P99 day | Max day |
|---|---:|---:|---:|---:|---:|
| Domain mean | 3.607 | 8.410 | 9.965 | 12.639 | 17.297 |
| Grid p90 | 11.400 | 27.900 | 32.485 | 43.580 | 58.070 |
| Grid p95 | 20.600 | 43.770 | 52.843 | 69.105 | 95.785 |
| Grid p99 | 44.000 | 88.500 | 103.643 | 149.662 | 203.755 |
| Grid maximum | 86.900 | 191.600 | 241.350 | 318.550 | 479.300 |

The units are retained from each source payload. No cross-provider common-mm threshold is defined here.

## IMERG × CMORPH day-to-day agreement across all 731 Development days

Agreement was calculated from the frozen 1,462 source-day rows.

| Metric | Pearson | Spearman |
|---|---:|---:|
| Domain mean | 0.968 | 0.974 |
| Grid p90 | 0.965 | 0.974 |
| Grid p95 | 0.958 | 0.966 |
| Grid p99 | 0.944 | 0.955 |
| Grid maximum | 0.870 | 0.889 |

Interpretation: broad daily wetness is highly reproducible across the two independent rainfall products. Agreement declines toward the localized maximum, consistent with the earlier Phase 2J finding that upper-tail/local-max rainfall is more provider-sensitive than spatially averaged rainfall.

## Where do the frozen LPZ-positive days sit?

The 65 frozen local episodes occur on only **22 unique UTC dates**. Therefore two views are retained:

1. Episode-weighted: preserves all 65 local episodes.
2. Unique-date: counts each UTC date once and avoids pretending that multiple local episodes on the same broad rain day are independent national-day samples.

### Unique-positive-date percentile rank within all 731 Development days

Median empirical percentile rank:

| Metric | IMERG | CMORPH |
|---|---:|---:|
| Domain mean | 80.44 | 81.53 |
| Grid p90 | 79.00 | 78.69 |
| Grid p95 | 85.50 | 82.52 |
| Grid p99 | 84.61 | 88.78 |
| Grid maximum | 86.80 | 92.95 |

Mean empirical percentile rank:

| Metric | IMERG | CMORPH |
|---|---:|---:|
| Domain mean | 76.75 | 78.51 |
| Grid p90 | 73.87 | 75.09 |
| Grid p95 | 75.49 | 77.63 |
| Grid p99 | 81.53 | 84.22 |
| Grid maximum | 84.22 | 87.14 |

Thus LPZ-positive dates are, as a population, strongly shifted toward wet/upper-tail days, especially in p99 and maximum rainfall. But they are **not universally among the most extreme Japan-domain days**.

For the 22 unique positive dates, counts at high Development percentiles were:

| Metric | >=P90 in both IMERG & CMORPH | >=P95 in both |
|---|---:|---:|
| Domain mean | 8 / 22 | 6 / 22 |
| Grid p90 | 7 / 22 | 6 / 22 |
| Grid p95 | 7 / 22 | 6 / 22 |
| Grid p99 | 7 / 22 | 7 / 22 |
| Grid maximum | 8 / 22 | 3 / 22 |

This is a central finding for the next phase: a national-domain daily maximum threshold would miss many known LPZ-positive dates and would confound regional organization with country-scale extremeness.

## Seasonality check

When each positive date is ranked only against the same calendar month across 2023–2024, median ranks become materially less extreme for several broad-domain metrics. Examples for unique positive dates:

- IMERG maximum median rank: 67.74 percentile within same calendar month.
- CMORPH maximum median rank: 84.42 percentile within same calendar month.
- IMERG p99 median rank: 70.52 percentile.
- CMORPH p99 median rank: 76.17 percentile.

Therefore seasonal climatology matters. A raw all-year daily threshold would partially encode season rather than LPZ-relevant rainfall structure.

## Scientific interpretation

Phase 2L-A supports four conclusions.

1. **LPZ positives preferentially occur on wet days**, but national-domain wetness alone is not a sufficient separator.
2. **Localized extremes are more provider-sensitive** than broad daily wetness, so a candidate rule should not rely on one provider's single-grid maximum.
3. **The 65 local LPZ episodes are clustered into 22 broad rain dates.** Episode and date are different statistical units and must remain separate.
4. **Spatial localization is now mandatory.** The next discovery phase must descend from the broad Japan-domain box to regional/JMA-primary-subdivision or spatial-hotspot summaries before constructing heavy-rain candidates.

This strengthens the original research question rather than solving it prematurely: the distinction between ordinary heavy rain and LPZ heavy rain cannot be reduced to “the LPZ day was simply a nationally wetter day.”

## Next phase — Phase 2L-B

Build a Development-only spatial heavy-rain candidate population while keeping Threshold and Hard Negative labels OFF.

Required design:

- Revisit daily IMERG and CMORPH grids only for spatial extraction.
- Use JMA primary-subdivision geometry and/or explicit connected rainfall-hotspot objects rather than the broad BBox scalar alone.
- Preserve provider-native rainfall independently.
- Explicitly exclude frozen realized-positive episode windows and embargo neighborhoods only after spatial/time overlap is defined.
- Quantify candidate population size, spatial duplication, temporal clustering, provider overlap/disagreement, seasonality, and coverage of the known positives as a sanity check.
- Do not yet call any candidate a Hard Negative.
- Do not choose a single common millimetre threshold across providers.
- Final severity matching will be done later from high-time-resolution 3-hour rainfall.
- GSMaP remains confirmatory and is not used to select candidates.

## Frozen guardrails

- `threshold_selected = false`
- `candidate_generated = false` in Phase 2L-A
- `hard_negative_label = null`
- `source_fusion_used = false`
- `gsmap_used_for_discovery = false`
- Validation 2025 unused
- Retrospective 2026 unused
- Prospective holdout unused
- `risk_score = null`
- `risk_engine_allowed = false`

No predictive claim is made by this phase.
