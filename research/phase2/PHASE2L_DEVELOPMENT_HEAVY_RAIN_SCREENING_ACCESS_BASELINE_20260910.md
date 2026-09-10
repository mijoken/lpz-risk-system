# Phase 2L — Development Heavy-Rain Screening Access Baseline

Date: 2026-09-10 JST

## Status

`PASS_DUAL_DAILY_SCREENING_PAYLOAD_PROOF`

Phase 2L begins the comparison problem: what separates strong-rain episodes that become JMA linear precipitation zones (LPZ) from strong-rain episodes that do not.

This baseline establishes the Development-wide discovery path only. No heavy-rain threshold, candidate label, hard-negative label, classifier, or risk score is selected here.

## Critical methodological correction

The existing 30-minute historical rainfall reconstruction was generated around frozen realized-positive anchors. It is therefore unsuitable as the sole sampling frame for finding non-LPZ heavy rain. Doing so would condition candidate discovery on proximity to positives and create selection bias.

Phase 2L therefore uses a two-stage design:

1. **Development-wide daily census** over 2023-2024 to discover potentially important rain region-days without conditioning on LPZ occurrence.
2. **Source-native 30-minute refinement** only for shortlisted region-days, reconstructing exact consecutive 3-hour rainfall windows using the already validated source-native rainfall-window machinery.

Daily precipitation is a screening variable only. It is not the final heavy-rain severity variable and will not be substituted for the 3-hour LPZ rainfall context.

## Provider access proof

### NASA IMERG Final V07 daily

- Earthdata short name: `GPM_3IMERGDF`
- Probe date: `2023-07-10`
- Retrieved file: `3B-DAY.MS.MRG.3IMERG.20230710-S000000-E235959.V07B.nc4`
- Main screening variable: `precipitation`
- Units: `mm/day`
- Grid: lon 3600 × lat 1800 = nominal 0.1-degree global grid
- Daily file also carries half-hourly valid-retrieval counts, allowing data-coverage diagnostics.

### NOAA CMORPH CDR daily

The historical public distribution was verified directly rather than inferred from guessed NCEI HTTPS paths.

Official public S3 bucket:

`noaa-cdr-precip-cmorph-pds`

Verified hierarchy:

- `data/30min/`
- `data/daily/`
- `data/hourly/`

Verified daily hierarchy:

- `data/daily/0.25deg/2023/`
- `data/daily/0.25deg/2024/`

Verified month hierarchy for 2023 contains all twelve month prefixes.

Verified exact daily key pattern by listing July 2023:

`data/daily/0.25deg/YYYY/MM/CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_YYYYMMDD.nc`

For the proof date:

`data/daily/0.25deg/2023/07/CMORPH_V1.0_ADJ_0.25deg-DLY_00Z_20230710.nc`

The July 2023 prefix contained exactly 31 daily NetCDF objects.

Decoded CMORPH daily payload:

- main variable: `cmorph`
- units: `mm/day`
- dimensions: time 1 × lat 480 × lon 1440
- nominal grid: 0.25 degrees

## Successful real-data proof

Dedicated dual-daily proof run:

`34428821091`

Result:

`SUCCESS`

Artifact:

`10133674103`

The workflow proved on the same Development date that:

- IMERG Final V07 daily retrieval succeeds;
- CMORPH official public-S3 daily retrieval succeeds;
- both NetCDF payloads decode scientifically;
- no threshold is selected;
- no candidate is generated;
- no hard-negative label is created;
- Validation is unused;
- Risk Engine remains OFF.

## Failed discovery attempts and what they taught us

Earlier Phase 2L probes intentionally failed closed while locating the historical CMORPH distribution:

- guessed NCEI daily HTTPS layouts returned 404;
- CPC's live monthly-tar index did not expose the requested 2023 month;
- broad recursive S3 listing was identified as unnecessarily expensive and rejected for production use.

These were provider-path discovery failures, not missing-data evidence. The final architecture now uses deterministic public-S3 daily keys and bounded prefix inspection; it does not recursively enumerate the full bucket.

## Candidate discovery policy — not yet a threshold

The next census must preserve the following separation between *description* and *selection*:

- First measure the complete Development 2023-2024 source-native daily rainfall distributions.
- Map each frozen Positive episode into those distributions.
- Quantify provider disagreement for region-day severity.
- Only then define a broad candidate-reservoir rule inside Development.
- Freeze that rule before any Validation 2025 inspection.

The candidate reservoir must be deliberately broad enough to contain ordinary heavy-rain mechanisms and must not be optimized to maximize LPZ/non-LPZ separation.

## Geographic design

Two views will be retained rather than silently choosing one:

1. **Matched-domain view** — primary-subdivision areas represented in frozen Development positives, reducing geographic confounding when asking the causal/scientific comparison question.
2. **National discovery view** — broader Japan-domain census so regions with no Development positive are not erased from natural heavy-rain prevalence.

The matched-domain view is appropriate for direct LPZ-vs-heavy-rain contrasts; the national view is appropriate for prevalence and robustness. Results will not be conflated.

## What will be compared after 3-hour refinement

For rainfall-matched LPZ positives and non-LPZ heavy-rain candidates, the analysis plan is:

1. source-native 3-hour severity: maximum, mean, p90, p95, p99;
2. ERA5 T0 environmental state: RH500, RH700, joint moist-area fraction, 600-hPa wind, 850-hPa wind, q1000/q925/q850;
3. precursor trajectory: T-180, -120, -90, -60, -30, T0;
4. season and region stratification;
5. IMERG/CMORPH robustness and disagreement;
6. redundancy-aware multivariate structure so correlated humidity variables are not counted as separate independent evidence;
7. episode-aware uncertainty and duplicate control;
8. later, true IWVF divergence/moisture-flux convergence only after the ERA5 descriptor is scientifically extended to support it.

No single humidity or wind threshold will be promoted from the Positive sample alone.

## Guardrails

- Development only: `true`
- Validation 2025 used: `false`
- Retrospective-test 2026 used: `false`
- Prospective holdout used: `false`
- Heavy-rain threshold selected: `false`
- Candidate generated: `false`
- Hard-negative label: `null`
- Rainfall-provider fusion: `false`
- GSMaP used: `false`
- Risk score: `null`
- Risk engine allowed: `false`

## Implemented infrastructure

- `scripts/phase2l_daily_screening_payload_probe.py`
- `.github/workflows/phase2l-cpc-monthly-daily-proof.yml` (renamed internally to Dual Daily Payload Proof)
- bounded CMORPH public-S3 hierarchy proof workflows

## Next gate

**Phase 2L-A: Development Daily Rainfall Census**

Build the 2023-2024 daily rainfall census without selecting a heavy-rain threshold. Produce source-native empirical distributions, geographic/seasonal coverage diagnostics, Positive percentile locations, and provider-disagreement diagnostics. Only after that descriptive census passes completeness and leakage checks may a broad Development-only heavy-rain candidate reservoir be frozen for 30-minute 3-hour refinement.
