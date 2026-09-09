# Phase 1C Parent Precursor Feature Table Baseline — 2026-09-09

## Status

**PASS — live parent-level feature table proven.**

GitHub Actions run 57 completed the full Phase 1C live chain and successfully built both:

- `reports/scientific/parent_precursor_features.json`
- `reports/scientific/parent_precursor_features.csv`

The table is descriptive only. It contains no classifier, LPZ score, stationarity threshold, or back-building threshold.

## Row unit

**One row = one tracked 30 mm/h parent-envelope lineage.**

Each row joins:

- duration and frame count;
- centroid displacement and path displacement;
- mean / median / maximum translation speed;
- IoU and overlap descriptors;
- area statistics;
- 50 and 80 mm/h embedded-core persistence;
- 50 and 80 mm/h core-genesis counts;
- genesis displacement relative to parent translation;
- genesis displacement relative to local 850-hPa meteorological inflow;
- local 850-hPa wind speed summaries;
- explicit boundary-truncation information.

No row receives a score or class label.

## Initial live result

Run 57 produced:

- total parent descriptors: **119**;
- non-boundary-truncated parents with at least one usable genesis event: **14**.

Two highly core-generative 15-minute parents illustrate why the feature axes must remain separate.

### T30-L0033

- duration: 15 min
- median translation speed: about 24.65 m/s
- median IoU: about 0.124
- embedded-core genesis count: 8
- usable genesis events: 8
- 50 mm/h behind-motion fraction: 4/7 = about 0.571
- 50 mm/h upstream-inflow fraction: 3/7 = about 0.429
- 50 mm/h behind-and-upstream fraction: 3/7 = about 0.429
- single usable 80 mm/h genesis event: neither behind-motion nor upstream-inflow in this sample

### T30-L0034

- duration: 15 min
- median translation speed: about 25.17 m/s
- median IoU: about 0.150
- embedded-core genesis count: 8
- usable genesis events: 8
- 50 mm/h behind-motion fraction: 3/5 = 0.60
- 50 mm/h upstream-inflow fraction: 2/5 = 0.40
- 50 mm/h behind-and-upstream fraction: 0/5 = 0.00
- 80 mm/h upstream-inflow fraction: 3/3 = 1.00
- 80 mm/h behind-motion fraction: 0/3 = 0.00

The two lineages have similar duration, translation speed, and total core-genesis count, yet very different joint geometry. Therefore a single hand-written "back-building" rule at this stage would discard scientifically relevant structure.

## Guardrails

1. `classification = null`.
2. `backbuilding_classification = null`.
3. `risk_score = null`.
4. Boundary-truncated genesis events are excluded from usable genesis summaries.
5. Parent translation and environmental inflow remain separate coordinate systems.
6. No threshold is learned or selected from this live case.
7. Historical positive and negative cases must be reconstructed before any feature selection or scoring.

## Next phase

The next major gate is **Historical Feature Reconstruction**.

For each historical positive and negative case, the same frozen feature definitions must be reconstructed at pre-event snapshots such as T-180, T-120, T-90, T-60, T-30, and T0 where data availability permits.

The historical table must include both:

- official / defensible LPZ-positive cases; and
- hard negatives such as intense convection, moving linear rainbands, short-lived organized rain, and heavy-rain events that did not satisfy the target LPZ definition.

Only after a temporally separated development / validation / final-holdout design is established may the project test whether any combination of duration, translation, overlap, core generation, parent-relative genesis, inflow-relative genesis, moisture, convergence, or other scientific features carries incremental predictive information.

## Risk engine

**NOT ALLOWED.**
