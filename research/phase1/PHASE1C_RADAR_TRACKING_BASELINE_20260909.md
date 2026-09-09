# Phase 1C Conservative Multi-Frame Radar Tracking Baseline — 2026-09-09

## Status

**PASS — conservative overlap-only multi-frame object tracking mechanics proven on live JMA HRPN data.**

Feature: `live_precip_object_tracking_public_png`

This baseline intentionally records both success and failure modes. It is not an LPZ persistence detector and does not apply Hirockawa persistence/overlap thresholds.

## Live proof

GitHub Actions run: **34333938273**

Fixed four-frame sequence:
- 2026-09-09T08:45:00Z
- 2026-09-09T08:50:00Z
- 2026-09-09T08:55:00Z
- 2026-09-09T09:00:00Z

Frame interval: **300 s**

Tracking footprint:
- fixed z8 4x4 tile mosaic
- same geographic footprint on all four frames
- exact public-PNG thresholds: 30 / 50 / 80 mm/h
- candidate lineage edge requires at least one overlapping pixel
- primary lineage: greedy one-to-one geometry match
- split/merge candidate edges preserved separately

The association score is an engineering geometry score only:

`0.50*IoU + 0.25*overlap_previous + 0.20*overlap_current + 0.05*proximity`

It has no meteorological LPZ meaning and is not used as a forecast threshold.

## >=30 mm/h outer precipitation objects

Frame component counts: **35, 42, 43, 46**.

| Transition | Candidate edges | Primary matches | Births | Deaths | Split candidates | Merge candidates |
|---|---:|---:|---:|---:|---:|---:|
| 08:45 -> 08:50 | 18 | 14 | 28 | 21 | 3 | 1 |
| 08:50 -> 08:55 | 17 | 14 | 29 | 28 | 2 | 1 |
| 08:55 -> 09:00 | 16 | 12 | 34 | 31 | 2 | 2 |

Primary-match median IoU by transition: **0.0346, 0.0967, 0.0967**.

Median centroid speed by transition: **16.14, 15.94, 16.56 m/s**. Maximum observed primary-match centroid speed was approximately **26.50 m/s**.

Lineage-duration distribution:
- 0 min: 98 lineages
- 5 min: 21
- 10 min: 2
- 15 min: 5

Five >=30 mm/h lineages were connected across all four frames. Their individual IoUs could still be low because precipitation shapes deform substantially while translating.

## >=50 mm/h embedded cores

Frame component counts: **9, 13, 10, 14**.

Primary matches by transition: **0, 2, 3**.

Lineage-duration distribution:
- 0 min: 38
- 5 min: 1
- 10 min: 2

No >=50 mm/h object could be overlap-linked from 08:45 to 08:50, despite the surrounding precipitation system remaining active.

## >=80 mm/h embedded cores

Frame component counts: **1, 2, 4, 6**.

Primary matches by transition: **0, 0, 1**.

Lineage-duration distribution:
- 0 min: 11
- 5 min: 1

The only overlap-linked >=80 mm/h transition had IoU **0.0816** and centroid speed approximately **14.44 m/s**.

## Interpretation

This is a useful negative result.

A strict overlap-only lineage is adequate as a **conservative proof of temporal association mechanics**, but it is too brittle to represent the lifecycle of intense convective cores. The >=50 and >=80 mm/h regions frequently appear, disappear, split, merge, or relocate inside a broader precipitation system over one 5-minute step.

Therefore the next tracker must not equate:

`same >=80 mm/h pixel object == same convective system`

A more defensible hierarchy is:
1. track the broader >=30 mm/h precipitation envelope as the parent system;
2. associate >=50 and >=80 mm/h objects as embedded child cores inside / near that parent;
3. preserve child genesis, decay, split, merge, and upstream birth separately;
4. derive stationarity from parent-system displacement/overlap, not from survival of one intense core.

This architecture is also better suited to future back-building evidence, where repeated new-core generation within/upstream of a persistent parent system is itself informative.

## Guardrails

- zero-overlap objects are not forcibly linked in this baseline
- split/merge evidence remains separate from primary lineage
- 15-minute survival is not called LPZ persistence
- no `overlap >= 0.5` LPZ rule is applied
- no speed threshold is an LPZ rule
- no lineage score enters a risk engine
- exact Hirockawa 3-h HRA remains blocked

## Scientific gates after this baseline

```text
fixed multi-frame radar mosaic              PASS
overlap-only temporal association           PASS
birth / death accounting                    PASS
split / merge candidate recording           PASS
centroid displacement / speed               PASS
hierarchical parent/core tracking           NEXT
stationarity descriptor                     PENDING
back-building descriptor                    PENDING
historical validation                       NOT STARTED
risk engine allowed                         NO
```
