# Phase 2D Positive Episode / Temporal Split Baseline

Date: 2026-09-10 JST

## Why this phase exists

The JMA official LPZ CSV is a regional detection table sampled repeatedly in time. Its 851 realized-positive anchors are not 851 independent meteorological events. Treating every row as independent would create severe pseudo-replication and would allow long-lived events to dominate validation statistics.

This phase freezes a conservative first-stage duplicate-control policy before any hard-negative payload or model evaluation.

## Conservative local episode definition

Anchors are grouped only when:

1. they have the same official JMA primary-subdivision code; and
2. consecutive anchor times are separated by no more than 20 minutes.

The 20-minute limit reflects the approximately 10-minute detection-table cadence and permits one missing cycle without merging longer discontinuities.

Cross-subdivision episode grouping is intentionally NOT performed yet. A validated historical rainfall/object field is required before linking detections across different official regions.

## Observed result on the frozen positive registry

- Realized-positive anchors: 851
- Local positive episodes: **119**
- Maximum anchors in one local episode: 30
- Median anchors per local episode: 4
- Maximum first-to-last-anchor duration: 290 minutes
- Median first-to-last-anchor duration: 30 minutes

### Frozen temporal partitions

| Split | Anchors | Local episodes | Semantics |
|---|---:|---:|---|
| DEVELOPMENT (2023-2024) | 501 | 65 | Feature discovery and descriptive research |
| VALIDATION (2025) | 213 | 34 | Frozen-rule validation only |
| RETROSPECTIVE_TEST_NON_PRISTINE (2026 before freeze) | 137 | 20 | Retrospective stress test only |
| PROSPECTIVE_HOLDOUT (from 2026-09-10 JST) | 0 | 0 | Future untouched evaluation |
| BOUNDARY_EMBARGO | 0 | 0 | +/- 6 h around split boundaries |

## Important interpretation

The effective number of independent meteorological systems may be smaller than 119 because one LPZ can be represented simultaneously in multiple adjacent primary subdivisions. Therefore:

- 851 must never be reported as the independent positive sample size;
- 119 is a conservative local-episode count, not yet a final nationwide meteorological-episode count;
- future cross-subdivision grouping must use validated spatial precipitation/object evidence rather than arbitrary region-name or distance rules.

## 2026 status and final holdout integrity

Pre-freeze 2026 data are explicitly labeled `RETROSPECTIVE_TEST_NON_PRISTINE`.

Reason: 2026 observations and live cases have already influenced architecture, source adapters, radar morphology, tracking, and scientific feature engineering. It would be methodologically false to rename those data an untouched Final Holdout now.

The prospective holdout is frozen to begin at:

`2026-09-10T00:00:00+09:00`

A +/- 6-hour split-boundary embargo is applied so that a meteorological episode cannot straddle two sets. No prospective observations existed in the official registry at this baseline run.

## Evaluation guardrails

1. Random row splitting is forbidden.
2. One local episode may not appear in more than one split.
3. Pre-freeze 2026 data may not be called Final Holdout.
4. Future prospective-holdout cases must not be used to revise thresholds, candidate rules, or feature definitions before evaluation is closed.
5. Anchor-level metrics, if ever reported, must be accompanied by episode-aware metrics or cluster-aware uncertainty; repeated detections from one episode cannot be treated as independent evidence.
6. Cross-subdivision episode grouping remains incomplete.
7. Hard-negative split assignment remains incomplete until the historical rainfall candidate population exists.
8. Risk Engine remains OFF.

## Evidence

- Episode/Split Proof Run: GitHub Actions Run 34372555927
- Unit and anti-leakage invariants: PASS
- 851/851 anchors assigned exactly once
- Cross-subdivision episode grouping: NOT COMPLETE
- Prospective holdout pristine by policy: TRUE
- Retrospective 2026 pristine: FALSE

## Implemented artifacts

- `config/historical_split_policy.json`
- `src/lpz_risk/historical_episodes.py`
- `scripts/build_positive_episode_registry.py`
- `tests/test_historical_episodes.py`
- `.github/workflows/historical-episode-proof.yml`

## Next scientific-data gate

Historical analyzed-rainfall payload is still required to:

1. construct real heavy-rain hard-negative candidates;
2. perform positive exclusion and duplicate control on the negative side;
3. derive spatial evidence that may later support cross-subdivision episode linkage;
4. freeze matched Development / Validation / Retrospective-Test negative populations.
