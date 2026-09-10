# Phase 2K — Development Positive Episode Environmental Baseline

Date: 2026-09-10 JST

## Status

`PASS_COMPLETE_DEVELOPMENT_POSITIVE_ENVIRONMENT_BASELINE`

This phase is descriptive only. It does **not** select a rainfall threshold, create hard-negative labels, inspect Validation 2025, inspect the 2026 retrospective test, inspect the prospective holdout, fuse rainfall providers, infer unavailable convergence fields, or enable the risk engine.

## Inputs and provenance

- Frozen positive split: DEVELOPMENT = 2023-2024
- Conservative Development local episodes: **65 / 65**
- Rainfall providers:
  - NASA IMERG Final V07
  - NOAA CMORPH CDR
- Rainfall representative policy: `EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER`
- Frozen Phase 2I rainfall source run: `34416417535`
- IMERG recovery run: `34421287940`
- Finalized ERA5 feature-table run: `34370550473`
- Phase 2K analysis run: `34423912911` — **SUCCESS**
- Phase 2K artifact: `10131921355`
- ERA5 precursor snapshots used: **390 / 390** = 65 episodes × 6 offsets
- Offsets: T-180, T-120, T-90, T-60, T-30, T0 minutes
- GSMaP: intentionally excluded while JAXA access remains under provider review

## Scientific semantics

ERA5 values are `PROXY_REANALYSIS` descriptors sampled from the configured JMA-primary-subdivision retrieval BBox. They are **not** subdivision-polygon means.

The currently available historical ERA5 descriptor supports:

- RH500
- RH700
- fraction of retrieval cells with RH500 and RH700 both >60%
- 600-hPa wind speed and direction
- 850-hPa wind speed and direction
- q1000, q925, q850

Three explicit descriptive composites are retained:

1. `midlevel_rh_mean_pct` = arithmetic mean of RH500 and RH700;
2. `low_level_q_mean_kgkg` = arithmetic mean of q1000, q925 and q850;
3. `wind850_600_direction_difference_deg` = circular difference of the reported 850/600-hPa mean-flow directions.

These are descriptive coordinates only. The third item is **not vector shear**, and narrowing of that angle is **not mass convergence**.

True evidence-defined IWVF divergence/moisture-flux convergence is not computed because the current historical ERA5 descriptor does not contain the required complete pressure-level set and horizontal derivatives. Status remains:

`NOT_AVAILABLE_IN_CURRENT_ERA5_DESCRIPTOR_DO_NOT_INFER`

## Positive-side environmental state

### Mean state across the 65 Development episodes

| Descriptor | T-180 min | T0 | Mean T0 − T-180 |
|---|---:|---:|---:|
| Mid-level RH mean | 83.420% | 82.420% | **-1.000 pp** |
| RH500/RH700 both >60% area fraction | 0.802 | 0.757 | **-0.0448** |
| Low-level q mean | 0.01585 kg/kg | 0.01572 kg/kg | **-0.000130 kg/kg** |
| 850-hPa wind speed | 16.167 m/s | 16.821 m/s | **+0.655 m/s** |
| 600-hPa wind speed | 19.619 m/s | 20.031 m/s | **+0.412 m/s** |
| 850/600-hPa direction difference | 33.592° | 27.970° | **-5.621°** |

At T0, the median mid-level RH is **83.313%** and the median RH500/RH700-both->60% fraction is **0.816**. The positive episodes therefore generally occupy an already-moist mid-level environment rather than showing a universal sharp moistening ramp during the last three hours.

The 850- and 600-hPa mean winds strengthen modestly toward T0 on average, while their reported mean-flow directions become more closely aligned. This is a directional-alignment observation only; it must not be relabeled as dynamical convergence.

## Rainfall-environment association — source native

No IMERG/CMORPH rainfall average is constructed. Correlations are calculated separately for each provider across the same 65 local episodes.

### Polygon maximum 3-hour accumulation — Spearman

| T0 environmental descriptor | IMERG | CMORPH |
|---|---:|---:|
| RH500/RH700 both >60% fraction | **0.576** | **0.676** |
| Mid-level RH mean | **0.560** | **0.592** |
| RH500 | 0.439 | 0.518 |
| RH700 | 0.488 | 0.414 |
| 600-hPa wind speed | 0.289 | 0.286 |
| 850-hPa wind speed | 0.170 | 0.034 |
| Low-level q mean | 0.135 | -0.109 |

### Polygon mean 3-hour accumulation — Spearman

| T0 environmental descriptor | IMERG | CMORPH |
|---|---:|---:|
| Mid-level RH mean | **0.677** | **0.697** |
| RH500/RH700 both >60% fraction | **0.639** | **0.691** |
| RH500 | 0.587 | 0.657 |
| RH700 | 0.500 | 0.426 |
| 600-hPa wind speed | 0.418 | 0.378 |
| 850-hPa wind speed | 0.255 | 0.161 |
| Low-level q mean | 0.037 | -0.137 |

The strongest source-robust descriptive relationship is therefore **mid-level environmental humidity at T0**. The relationship is stronger for polygon-mean rainfall than for the localized polygon maximum, consistent with the Phase 2J observation that spatial means are more stable between rainfall products than local extremes.

Low-level specific humidity is physically important to heavy-rain systems, but in this positive-only 65-episode sample its simple BBox mean has much weaker direct cross-episode association with rainfall amount. This must **not** be interpreted as evidence that low-level moisture is dynamically unimportant. Season, geography, BBox sampling, source-product response and positive-only range restriction can all weaken a simple marginal correlation.

## Absolute state versus recent trajectory

The T-180→T0 change variables are generally less consistently associated with rainfall magnitude than the T0 absolute humidity state.

Examples of Spearman association for the 600-hPa wind-speed increase:

- IMERG maximum: 0.187
- IMERG mean: 0.344
- CMORPH maximum: 0.038
- CMORPH mean: 0.237

For mid-level RH T0−T-180 change:

- IMERG maximum: 0.148
- IMERG mean: 0.141
- CMORPH maximum: 0.132
- CMORPH mean: 0.086

This indicates that, within realized positive episodes, **being in a moist environmental state is currently a clearer descriptive coordinate than the amount of moistening during the preceding three hours**. No predictive claim is made.

## Internal multivariate structure

Several candidate coordinates are strongly redundant and must not later be treated as independent evidence simply because they have different names.

Selected Development Spearman correlations:

- q925 vs low-level-q composite: **0.972**
- RH500/RH700-both->60% fraction vs mid-level-RH composite: **0.938**
- RH500 vs mid-level-RH composite: **0.909**
- q1000 vs low-level-q composite: **0.922**
- RH500 vs RH500/RH700-both->60% fraction: **0.872**
- 600-hPa wind speed vs 850-hPa wind speed: **0.822**
- 600-hPa wind speed vs 850/600 direction difference: **-0.519**

This matters for future feature design: naïvely adding all of these as separate positive votes would double- or triple-count the same environmental structure.

## ERA5 value-quality note

The source-native ERA5 RH means are intentionally not clipped in this phase. Across the selected 390 snapshots:

- RH500 mean >100%: **38 / 390** snapshots; maximum 103.923%
- RH700 mean >100%: **4 / 390** snapshots; maximum 102.361%
- RH below 0%: **0** snapshots
- non-finite values in the retained q/wind descriptors: **0**

This does not invalidate the descriptive baseline, but any future thresholding or normalization must decide explicitly whether source-native supersaturation values are retained, capped, or transformed. That choice must be frozen before Validation use.

## Interpretation for Hard Negative design

Phase 2K provides the first positive-side environmental reference coordinates without using Validation or constructing a classifier.

The important result is not a single threshold. It is the structure:

1. realized LPZ positives commonly sit in a broadly moist mid-level environment;
2. T0 mid-level humidity shows the most reproducible relation to rainfall magnitude across both IMERG and CMORPH;
3. 600-hPa flow strength contributes a weaker but source-consistent second dimension;
4. low-level q and recent 3-hour changes are not clean one-dimensional separators in the positive-only sample;
5. several humidity and wind coordinates are highly correlated, so future matching must control redundancy;
6. rainfall-provider disagreement remains explicit and must not be hidden through fusion.

Therefore the future Hard Negative problem should be framed as:

> find heavy-rain non-LPZ episodes that occupy rainfall severity comparable to positive episodes, then ask whether their **multivariate environmental coordinates** differ from the frozen positive reference distribution.

It should **not** be framed as selecting one RH or wind cutoff from positives and labeling everything else negative.

## Guardrails

- Candidate threshold selected: `false`
- Hard-negative label: `null`
- Validation data used: `false`
- Retrospective-test data used: `false`
- Prospective-holdout data used: `false`
- GSMaP used: `false`
- Rainfall source fusion used: `false`
- Convergence inferred: `false`
- Risk score: `null`
- Risk engine allowed: `false`
- Cross-subdivision episode grouping: not complete

## Implemented artifacts

- `src/lpz_risk/positive_environment_baseline.py`
- `scripts/analyze_development_positive_environment.py`
- `tests/test_positive_environment_baseline.py`
- `.github/workflows/development-positive-environment-baseline.yml`
- `research/phase2/POSITIVE_ENVIRONMENT_BASELINE_TRIGGER.txt`

Scientific CI passed after the new focused tests were introduced, and the dedicated Phase 2K real-data workflow completed successfully.

## Next scientific-data gate

The next high-value step is to construct a **Development-only heavy-rain candidate population** from the historical rainfall products while preserving source-native severity and excluding all frozen realized-positive windows/embargo neighborhoods. At that stage, no hard-negative threshold should yet be selected. The first objective is to measure candidate-pool coverage, duplication, provider disagreement and environmental overlap against this Phase 2K positive reference.
