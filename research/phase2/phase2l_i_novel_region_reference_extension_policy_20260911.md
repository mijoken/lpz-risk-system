# Phase 2L-I — Novel-Region Reference Extension Policy

**Gate:** `PASS_PHASE2L_I_NOVEL_REGION_REFERENCE_EXTENSION_POLICY_FROZEN_PRE_RAINFALL_ENVIRONMENT`  
**Frozen at UTC:** `2026-09-11T11:09:34.085889Z`

## Status of this amendment

This is a **post-label-open, pre-rainfall/pre-ERA5 protocol amendment**.

It is **not** represented as part of the original Phase 2L-H pre-validation
freeze.

At the time of this amendment:

- 2025 Positive region-days known: **23**
- covered by the original 45-region Development reference: **12**
- novel-region Positive region-days: **11**
- novel fraction: **47.83%**
- novel region codes: `020010, 130030, 140010, 220010, 220020, 350010, 430030, 460010, 460020`
- 2025 rainfall read: **NO**
- 2025 ERA5/environment read: **NO**

## Frozen decision

Novel-region Positive cases will **not** be discarded.

For the novel primary subdivisions, the same CMORPH reference distribution will
be reconstructed using **2023-2024 only** (731 days), with the same JMA geometry,
bbox, and +0.5 degree padding semantics as Development.

No 2025 rainfall is used to define any threshold.

## Frozen out-of-sample CMORPH rule

For each region and each of:

- `rain_max_mm_day`
- `rain_p90_mm_day`
- `rain_p95_mm_day`

calculate the 2023-2024 pandas average percentile ranks. The fixed numeric
cutoff is the minimum Development value among days with percentile rank >= 80.

Before 2025 screening is allowed, applying those cutoffs to the original 45
Development regions must reproduce the frozen **5,943 region-day reservoir
exactly**.

For the 9 novel regions, the identical algorithm is applied to their 2023-2024
731-day reference distributions.

## Positive eligibility

Official 2025 Positive cases remain eligible **even if their own CMORPH day does
not pass the screening rule**.

The CMORPH screen defines the **Comparison candidate pool**, not Positive
eligibility.

## Frozen IMERG/matching transfer

- No PCA refit on 2025.
- Use Development log1p mean/std and PCA loadings.
- Match on frozen PC1/PC2.
- Same primary subdivision.
- +/-60 calendar days.
- Exclude +/-3 actual days around same-region Positives.
- 1:3.
- No replacement.

If a Positive has fewer than 3 eligible comparisons, it is marked
`UNMATCHABLE_UNDER_FROZEN_PROTOCOL`. Parameters are not relaxed.

## Primary hypothesis

Unchanged:

`q850_mean_kgkg @ t+0h`, Positive higher.

Cluster unit and confirmatory test are unchanged from Phase 2L-H.

## Novel regions

`020010, 130030, 140010, 220010, 220020, 350010, 430030, 460010, 460020`

## Scientific guardrails

No 2025 rainfall or ERA5 was read before this amendment.
No 2025 threshold estimation is allowed.
No hard-negative label is created.
Risk engine remains disabled.
