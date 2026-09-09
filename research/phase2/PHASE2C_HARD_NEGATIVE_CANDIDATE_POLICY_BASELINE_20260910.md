# Phase 2C Hard Negative Candidate Policy Baseline

Date: 2026-09-10 JST

## Purpose

Freeze the rainfall-based candidate-generation policy before inspecting the actual historical analyzed-rainfall payload. This prevents outcome-driven or model-error-driven negative selection.

## Source gate

Required rainfall source: `JMA_ANALYZED_RAINFALL_ANNUAL_2017_PLUS`.

JMA's official information catalogue identifies analyzed rainfall as a 1 km, one-hour precipitation GRIB2 product. Historical `解析雨量データ` from 2017 onward is issued annually through JMA viewing / Japan Meteorological Business Support Center media or another permitted equivalent route.

Current status: `ACCESS_PATH_IDENTIFIED_PAYLOAD_NOT_ACQUIRED`.

No public bulk API is assumed.

## Broad candidate entry rule

A three-hour analyzed-rainfall screening record enters the broad candidate pool when either condition is true:

1. maximum three-hour accumulation >= 80 mm; OR
2. area with three-hour accumulation >= 80 mm is >= 500 km².

This broad rule is intentionally more permissive than the full official LPZ definition. It is a candidate-screening rule, not a classification rule.

## Descriptive strength tags

Candidates may carry zero or more of the following descriptive tags:

- `MAX3H_GE_100`
- `MAX3H_GE_150`
- `AREA80_GE_500`
- `AREA100_GE_500`
- `RAIN_ONLY_NEAR_OFFICIAL_INTENSITY` = area >=100 mm reaches 500 km² AND maximum accumulation >=150 mm

These tags never assign `HARD_NEGATIVE` by themselves.

## Positive exclusion

For the same JMA primary subdivision, candidates within -180 to +180 minutes of an official realized-positive anchor are marked `EXCLUDED_NEAR_OFFICIAL_POSITIVE`.

This exclusion is applied before later train/validation/holdout assignment.

## Entity semantics

Generated entities are:

`HARD_NEGATIVE_CANDIDATE`

with status:

- `UNCONFIRMED_HARD_NEGATIVE_CANDIDATE`, or
- `EXCLUDED_NEAR_OFFICIAL_POSITIVE`.

The following fields remain null/false:

- `hard_negative_label = null`
- `lpz_classification = null`
- `risk_score = null`
- `hard_negative_registry_complete = false`
- `hard_negative_label_allowed = false`
- `risk_engine_allowed = false`

## Confirmation gates still required

A candidate cannot become a final Hard Negative until all relevant gates are satisfied:

1. actual historical analyzed-rainfall payload is audited;
2. candidate is outside the positive exclusion window;
3. episode grouping or equivalent duplicate control is complete;
4. candidate selection has not used model outputs/errors;
5. temporal split assignment is frozen before model evaluation;
6. morphology-dependent categories remain unavailable unless a suitable historical high-resolution radar source is separately audited.

## Forbidden shortcuts

- random sunny-day controls as the primary negative population;
- choosing negatives after observing model errors;
- assigning final negative labels from rainfall thresholds alone;
- treating 1 km analyzed rainfall as equivalent to 250 m instantaneous radar morphology;
- using JMA LPZ forecasts or KIKIKURU as model features.

## Implemented artifacts

- `config/hard_negative_candidate_policy.json`
- `src/lpz_risk/hard_negative_candidates.py`
- `scripts/build_hard_negative_candidates.py`
- `tests/test_hard_negative_candidates.py`

## Next data step

Obtain and audit at least one actual annual JMA analyzed-rainfall payload from the permitted historical route. The first payload proof must validate GRIB2 decoding, valid-time semantics, grid geometry, missing-value conventions, precipitation units, and consistency of consecutive one-hour fields before any real candidate registry is generated.
