# Phase 1C 850-hPa Inflow-Relative Genesis Baseline — 2026-09-09

## Status

**PASS — live scientific descriptor proven.**

GitHub Actions run 54 completed the full chain:

`radar decode -> morphology -> 600-hPa orientation -> tracking -> hierarchy -> temporal descriptors -> parent-motion genesis geometry -> 850-hPa inflow-relative genesis geometry`

All workflow steps completed successfully.

## Time alignment

Live event window:
- first genesis time: 2026-09-09 09:45 UTC
- last genesis time: 2026-09-09 09:55 UTC
- representative time: 2026-09-09 09:50 UTC

Selected GFS field:
- model cycle: 2026-09-09 00:00 UTC
- forecast hour: f010
- forecast valid time: 2026-09-09 10:00 UTC
- representative-time mismatch: 10 minutes

The model cycle is conservatively at least four hours older than the latest radar event, preserving the no-future-information policy used for historical reconstruction.

## Descriptor definition

For each newly observed 50/80 mm/h child core inside a continuing 30 mm/h parent envelope, the child-centroid displacement from the current parent centroid is projected onto the local 850-hPa meteorological wind-FROM direction.

- `along_inflow_km > 0`: genesis lies toward the meteorological wind-FROM / upstream / inflow side.
- `along_inflow_km < 0`: genesis lies on the downwind side.
- `cross_inflow_km`: perpendicular displacement.
- `genesis_vs_inflow_from_angle_deg`: angular separation between the parent-to-child genesis vector and the local wind-FROM direction.

This coordinate system is intentionally independent of parent translation (`along_motion_km`).

## Initial live descriptive sample

After excluding boundary-truncated parents:

### 50 mm/h child-core genesis
- usable events: 25
- upstream-side events: 11
- downwind-side events: 14
- upstream fraction: 0.44
- median `along_inflow_km`: -0.126 km
- median genesis-vs-inflow angle: 92.35 degrees

### 80 mm/h child-core genesis
- usable events: 4
- upstream-side events: 3
- downwind-side events: 1
- upstream fraction: 0.75
- median `along_inflow_km`: +0.435 km
- median genesis-vs-inflow angle: 34.33 degrees

These values describe one short live case only.

## Important negative result

Parent-motion geometry and low-level inflow geometry are demonstrably not interchangeable in this sample.

Among untruncated events with both descriptors:

- 50 mm/h: `behind parent motion AND upstream inflow side` = 2 of 25.
- 80 mm/h: `behind parent motion AND upstream inflow side` = 0 of 4.

Therefore the system must preserve translation-relative and inflow-relative genesis as separate axes. A rule such as "genesis behind the system means upstream/back-building" would be scientifically unsafe.

## Guardrails

1. No upstream fraction threshold is an operational gate.
2. No `backbuilding=true/false` field is emitted.
3. 850-hPa wind is an environmental descriptor, not assumed to be a complete representation of boundary-layer moisture inflow.
4. Historical positive and negative cases are required before inference.
5. Risk engine remains blocked.

## Next gate

Build a **per-parent composite precursor descriptor** that joins, without scoring:

- parent duration and translation speed;
- spatial overlap / IoU;
- 50/80 mm/h embedded-core presence;
- core genesis counts;
- genesis relative to parent motion;
- genesis relative to 850-hPa inflow.

This composite table is an Evidence-DB feature layer, not a classifier.
