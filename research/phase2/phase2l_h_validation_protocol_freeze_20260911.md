# Phase 2L-H — Discovery & 2025 Validation Protocol Freeze

**Gate:** `PASS_PHASE2L_H_DISCOVERY_AND_VALIDATION_PROTOCOL_FREEZE_PRIMARY_Q850_T0H`  
**Frozen at (UTC):** `2026-09-11T10:50:43.524724Z`  
**Validation year:** 2025 — **UNTOUCHED at freeze**

## Primary hypothesis

`q850_mean_kgkg @ t+0h`

Directional hypothesis:

> Among rainfall-severity-matched heavy-rain cases, LPZ Positive cases have
> higher ERA5 850-hPa specific humidity at the start of the IMERG P95-max
> 3-hour rainfall window than the mean of their three matched Comparison cases.

This is the **only primary confirmatory hypothesis**.

## Frozen matched estimand

For every match set:

`Positive - mean(3 matched Comparisons)`

Match-set differences are then aggregated within `positive_date_utc`.
The primary effect estimate is the **equal-weight mean of UTC-date cluster
means**.

## Frozen primary validation test

- Exact **one-sided sign test** on `positive_date_utc` cluster means.
- Alternative: cluster mean difference `> 0`.
- Zero differences are ignored.
- Alpha: `0.05`.
- No multiplicity correction is applied to this single pre-specified Primary.
- Primary confirmation requires:
  1. primary effect estimate `> 0`, and
  2. one-sided exact sign-test `p < 0.05`.

Secondary/exploratory findings **cannot rescue a failed Primary**.

## Pre-specified robustness

- 20,000-resample cluster bootstrap; supportive if 95% CI lower bound `> 0`.
- Leave-one-positive-date-out; supportive if same-sign fraction is `1.0`
  and the LODO mean range does not cross zero.

## Secondary / exploratory hypotheses

[
  {
    "metric": "q925_mean_kgkg",
    "contrast": "t-3h",
    "direction": "POSITIVE_HIGHER",
    "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY"
  },
  {
    "metric": "q925_mean_kgkg",
    "contrast": "t-6h",
    "direction": "POSITIVE_HIGHER",
    "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY"
  },
  {
    "metric": "wind600_speed_mean_mps",
    "contrast": "t+0h",
    "direction": "POSITIVE_HIGHER",
    "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY"
  },
  {
    "metric": "q850_mean_kgkg",
    "contrast": "persistence_mean",
    "direction": "POSITIVE_HIGHER",
    "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY"
  },
  {
    "metric": "q850_mean_kgkg",
    "contrast": "delta_-6h_to_0h",
    "direction": "POSITIVE_HIGHER",
    "status": "SECONDARY_PRE_SPECIFIED_NOT_PRIMARY"
  },
  {
    "metric": "rh500_mean_pct",
    "contrast": "delta_-3h_to_0h",
    "direction": "POSITIVE_LOWER",
    "status": "MECHANISTIC_EXPLORATORY_PRE_SPECIFIED"
  }
]

## Development evidence that motivated the freeze

Phase 2L-F:

- paired effect dz: `0.700207`
- two-sided sign-test p: `0.000009063`
- 81-test BH-FDR q: `0.000734`

Phase 2L-G:

- cluster effect dz: `0.662357`
- two-sided date sign-test p: `0.004343510`
- 81-test BH-FDR q: `0.351824`
- cluster bootstrap CI excludes zero: `True`
- LODO same-sign fraction: `1.000000`
- LODO crosses zero: `False`

Interpretation: strong Development candidate, **not** multiplicity-confirmed in
the 81-test discovery panel. Independent 2025 validation is therefore required.

## Scientific guardrails

- Matching membership remains frozen from Phase 2L-D.
- Environment variables never alter membership.
- Comparison cases are **not Negative labels**.
- No new primary variable, time offset, threshold, or direction may be chosen
  after 2025 outcomes are opened.
- 850-hPa metrics are **not Kato 500-m FLWV**.
- Validation 2025 cannot be used to tune the Primary.
- Retrospective 2026 and prospective holdout remain untouched.
- Risk engine remains disabled.

## Integrity

Exact source-code and source-artifact SHA256 values are stored in:

`research\phase2\phase2l_h_validation_protocol_freeze_20260911.json`

Git HEAD before the freeze commit:

`ff2d36a8ff28c8b23743db29e1989005cd011334`

This file must be committed before Phase 2L validation outcome analysis begins.
