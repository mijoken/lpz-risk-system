# Phase 2L-K2 — IMERG Final V07 Boundary / V08 Deferred Validation Freeze

**Gate:** `PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE`  
**Frozen at:** `2026-09-12T00:03:31.380785Z`

## Decision

The 2025 confirmatory Primary validation is **deferred**, not failed.

IMERG Final V07 ends at **2025-09-30 23:30 UTC**. The entire V07-supported
2025 target segment has been reconstructed successfully, but the frozen
rainfall-matching universe is not fully observable for any of the 23 Positive
region-days. Therefore the exact pre-specified 1:3 matching cannot be completed
without changing the frozen protocol.

## Verified source boundary

- 2025 IMERG refinement targets: **1218**
- Unique target UTC days: **191**
- V07-supported region-days: **1004**
- V07-unavailable region-days: **214**
- V07-supported target days: **143**
- Valid supported-day checkpoints: **143 / 143**
- V07-unavailable target days: **48**
- Positive region-days: **23**
- Positive region-days supported by V07: **22**
- Positive region-days unavailable under V07: **1**
- Fully observed frozen matching universes: **0 / 23**

## Frozen Primary remains unchanged

- Metric: `q850_mean_kgkg`
- Contrast: `t+0h`
- Direction: Positive > mean of 3 rainfall-matched Comparisons
- Primary confirmatory test has **not** been run.
- 2025 ERA5 environmental outcomes remain **sealed**.
- Risk engine remains **locked**.

## Work allowed while waiting for Final V08

- `SOURCE_HEALTH_MONITORING_AND_VERSION_DETECTION`
- `PROSPECTIVE_DATA_COLLECTION_WITHOUT_OUTCOME_DRIVEN_MODEL_SELECTION`
- `CHECKPOINT_RESUME_AND_AUDIT_INFRASTRUCTURE`
- `DATABASE_AND_SCHEMA_IMPLEMENTATION`
- `END_TO_END_PIPELINE_ORCHESTRATION_WITHOUT_2025_ENVIRONMENT_OUTCOME_OPENING`
- `DASHBOARD_AND_UI_IMPLEMENTATION_WITH_RISK_ENGINE_LOCKED`
- `WINDOWS_SCHEDULER_AND_RECOVERY_AUTOMATION`
- `V8_MIGRATION_AND_REBUILD_CODE_IMPLEMENTATION_USING_MOCK_OR_DEVELOPMENT_DATA`
- `TESTS_DOCUMENTATION_AND_OPERATIONAL_HARDENING`

## Prohibited while waiting for Final V08

- `DO_NOT_OPEN_2025_ERA5_ENVIRONMENT_FOR_PRIMARY_VALIDATION_BEFORE_RAINFALL_MATCHING_IS_RESOLVED`
- `DO_NOT_SUBSTITUTE_IMERG_LATE_OR_EARLY_FOR_FINAL_PRIMARY_VALIDATION`
- `DO_NOT_SUBSTITUTE_GSMAP_CMORPH_OR_OTHER_SATELLITE_FOR_MISSING_FINAL_IMERG_TARGETS`
- `DO_NOT_FILL_ONLY_2025_OCT_DEC_WITH_A_DIFFERENT_IMERG_VERSION`
- `DO_NOT_DROP_V07_UNAVAILABLE_2025_TARGETS_TO_FORCE_COMPLETION`
- `DO_NOT_SHRINK_OR_EXPAND_THE_FROZEN_PLUS_MINUS_60_DAY_SEASON_WINDOW`
- `DO_NOT_CHANGE_THE_PLUS_MINUS_3_DAY_POSITIVE_EVENT_BUFFER`
- `DO_NOT_CHANGE_THE_1_TO_3_NO_REPLACEMENT_MATCHING_POLICY`
- `DO_NOT_REFIT_PCA_OR_STANDARDIZATION_USING_2025_VALIDATION_DATA`
- `DO_NOT_CHANGE_PRIMARY_METRIC_TIME_OFFSET_DIRECTION_OR_TEST`
- `DO_NOT_PROMOTE_SECONDARY_OR_EXPLORATORY_FEATURES_TO_RESCUE_PRIMARY`
- `DO_NOT_USE_2026_RETROSPECTIVE_OR_PROSPECTIVE_OUTCOMES_FOR_MODEL_SELECTION`
- `DO_NOT_ENABLE_RISK_ENGINE_BEFORE_CONFIRMATORY_VALIDATION_IS_RESOLVED`

## Final V08 re-entry sequence

1. `OFFICIAL_NASA_IMERG_FINAL_V08_IS_PUBLICLY_AVAILABLE`
2. `FINAL_V08_HALF_HOURLY_PRODUCT_COVERS_ALL_REQUIRED_2023_2024_DEVELOPMENT_AND_2025_VALIDATION_DATES`
3. `REBUILD_THE_FROZEN_5943_DEVELOPMENT_IMERG_REGION_DAYS_USING_FINAL_V08`
4. `REBUILD_THE_FROZEN_1218_2025_VALIDATION_TARGET_REGION_DAYS_USING_THE_SAME_FINAL_V08_PRODUCT`
5. `REESTIMATE_LOG1P_MEAN_STD_AND_PCA_LOADINGS_FROM_DEVELOPMENT_V08_ONLY`
6. `TRANSFER_THE_DEVELOPMENT_V08_TRANSFORM_TO_2025_WITHOUT_2025_REFIT`
7. `REAPPLY_THE_FROZEN_SAME_REGION_PLUS_MINUS_60_DAY_PLUS_MINUS_3_DAY_1_TO_3_NO_REPLACEMENT_MATCHING`
8. `FREEZE_THE_FINAL_2025_MATCHED_POPULATION`
9. `ONLY_AFTER_MATCHING_FREEZE_OPEN_2025_ERA5_ENVIRONMENT_OUTCOMES`
10. `RUN_THE_SINGLE_FROZEN_Q850_T0H_CONFIRMATORY_TEST_ONCE`
11. `DO_NOT_RETUNE_AFTER_PASS_OR_FAIL`

## Critical version rule

Do **not** patch only October–December 2025 with V08. Development 2023–2024
and Validation 2025 must be rebuilt using the same Final V08 product family.
The rainfall transform may be re-estimated from Development V08 only and then
transferred to 2025 without validation refitting.

## Next active phase

**Phase 2L-L — Source Health and Operational Readiness**

The research confirmation branch is frozen. Operational V1 development may
continue.
