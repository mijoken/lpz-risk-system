# Phase 2J — IMERG + CMORPH Development Source-Disagreement Baseline

Date: 2026-09-10 JST

## Status

`PASS_COMPLETE_DUAL_SOURCE_DEVELOPMENT_DESCRIPTIVE_ANALYSIS`

This phase is descriptive only. It does **not** select a rainfall threshold, create hard-negative labels, inspect Validation 2025, inspect the 2026 retrospective test, inspect the prospective holdout, or enable the risk engine.

## Inputs and provenance

- Frozen Phase 2I source plan: GitHub Actions run `34416417535`
- IMERG-only recovery run: `34421287940` — SUCCESS
- Dual-source analysis run: `34421481067` — SUCCESS
- Analysis artifact: `10131054998`
- Providers:
  - NASA IMERG Final V07
  - NOAA CMORPH CDR
- Pairing unit: conservative local episode ID
- Representative policy: `EARLIEST_REALIZED_POSITIVE_ANCHOR_PER_LOCAL_EPISODE_PROVIDER`
- Complete paired Development episodes: **65 / 65**
- Cross-subdivision episode grouping remains incomplete.
- GSMaP is intentionally excluded while JAXA access is under provider review.

## Main result — polygon maximum 3-hour accumulation

### IMERG Final V07

- n = 65
- mean = **37.576 mm**
- min = 1.080 mm
- median = **37.660 mm**
- p75 = 49.575 mm
- p90 = 62.145 mm
- p95 = 72.710 mm
- p99 = 95.902 mm
- max = 118.360 mm

### CMORPH CDR

- n = 65
- mean = **47.370 mm**
- min = 0.420 mm
- median = **46.330 mm**
- p75 = 63.355 mm
- p90 = 77.665 mm
- p95 = 93.880 mm
- p99 = 103.664 mm
- max = 104.080 mm

### IMERG minus CMORPH

- mean difference = **-9.794 mm**
- median difference = -5.810 mm
- mean absolute difference = **13.997 mm**
- median absolute difference = 8.580 mm
- p90 absolute difference = 32.685 mm
- maximum absolute difference = 46.160 mm

### Association

- Pearson correlation = **0.7845**
- Spearman rank correlation = **0.7397**
- empirical top-decile set size = 7 episodes/provider
- top-decile overlap = **3 / 7**
- top-decile Jaccard = **0.2727**

Interpretation: the two independent products broadly co-vary across Development LPZ episodes, but the absolute magnitude and the ordering of the most extreme episodes differ materially. Therefore provider disagreement must remain explicit data-quality/provenance information and must not be hidden by averaging.

## Polygon mean 3-hour accumulation

### IMERG
- mean = 20.769 mm
- median = 14.682 mm
- p90 = 41.250 mm
- p95 = 47.895 mm
- max = 58.931 mm

### CMORPH
- mean = 25.947 mm
- median = 22.650 mm
- p90 = 47.368 mm
- p95 = 60.008 mm
- max = 82.427 mm

Association:
- Pearson = **0.8790**
- Spearman = **0.8665**
- top-decile overlap = **5 / 7**

The spatial mean agrees more strongly than the polygon maximum. This is scientifically plausible for coarse precipitation products: localized maxima are more sensitive to retrieval, sampling, grid placement and algorithm differences than broader-area mean rainfall.

## Upper-tail polygon statistics

| Metric | Pearson | Spearman | Mean IMERG-CMORPH difference | Mean absolute difference | Top-decile overlap |
|---|---:|---:|---:|---:|---:|
| p90 accumulation | 0.8221 | 0.7657 | -7.309 mm | 11.393 mm | 5/7 |
| p95 accumulation | 0.8257 | 0.7688 | -8.541 mm | 11.844 mm | 4/7 |
| p99 accumulation | 0.8047 | 0.7524 | -9.369 mm | 13.220 mm | 3/7 |
| maximum | 0.7845 | 0.7397 | -9.794 mm | 13.997 mm | 3/7 |

Agreement weakens as the statistic moves toward the most localized extreme. This argues against deriving a common absolute threshold by simply treating IMERG and CMORPH millimetres as interchangeable.

## Ratio caution

Provider ratios become unstable when the denominator is near zero. Although ratios are retained as descriptive diagnostics, they must not be used directly as calibration variables without a denominator floor or log-ratio treatment. Absolute differences and paired ranks are safer primary disagreement descriptors.

## Scientific consequences for the next phase

1. Do **not** average IMERG and CMORPH into a synthetic rainfall field.
2. Do **not** transplant a single common millimetre threshold between providers.
3. Calibrate source-native distributions independently.
4. Treat cross-provider concurrence/disagreement as a confidence or data-quality dimension, not as hidden fusion.
5. Preserve episode-level pairing to avoid pseudo-replication from repeated 10-minute official anchors.
6. Keep threshold selection frozen until GSMaP is restored or a separately reviewed source-policy decision formally changes the three-provider design.
7. Validation 2025 remains untouched.

## Guardrails

- Candidate threshold selected: `false`
- Hard-negative label: `null`
- Validation data used: `false`
- Retrospective-test data used: `false`
- Prospective-holdout data used: `false`
- Risk score: `null`
- Risk engine allowed: `false`

## Conclusion

The IMERG + CMORPH free historical stack is now complete for all 65 conservative Development local episodes and is scientifically useful, but the products are not interchangeable in the upper tail. Their disagreement is itself an important observable. Phase 2J therefore closes as a **descriptive source-disagreement baseline**, not a threshold-calibration result.
