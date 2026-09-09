# Phase 1C Genesis Relative-Motion Baseline — 2026-09-09

## Status

**PASS — descriptive geometry only.**

The embedded-core genesis geometry implementation and its unit tests are now CI-validated. GitHub Actions run 51 (`test: validate embedded core relative motion geometry`) completed successfully.

This baseline freezes a purely geometric descriptor. It does **not** classify back-building and is not an LPZ risk gate.

## Definition

For each newly observed 50 or 80 mm/h child core embedded in a continuing 30 mm/h parent envelope:

- the parent displacement over the preceding 5 minutes defines the translating-system motion axis;
- `along_motion_km > 0` means the child centroid lies ahead of the current parent centroid along that motion axis;
- `along_motion_km < 0` means the child centroid lies behind the current parent centroid;
- `cross_motion_km` preserves the perpendicular displacement;
- zero-motion parents retain relative distance but leave along/cross motion undefined.

The implementation is intentionally explicit that `along_motion_km < 0` is **not equivalent to back-building**.

## Initial live descriptive result

The first live 15-minute proof produced the following untruncated-parent descriptive sample:

- 50 mm/h genesis cores: 13 usable events; 5 behind the parent-motion axis; median `along_motion_km` about +0.52 km.
- 80 mm/h genesis cores: 9 usable events; 7 behind the parent-motion axis; median `along_motion_km` about -1.96 km.

These figures are a single live case and must not be treated as climatological probabilities, thresholds, or evidence of predictive skill.

## Scientific guardrails

1. No `backbuilding=true/false` label is emitted.
2. No threshold on `along_motion_km` is promoted into the risk engine.
3. Boundary-truncated parent objects are excluded from the descriptive summary.
4. Environmental inflow direction is a separate feature and must not be conflated with parent translation.
5. Historical positive and negative cases are required before any operational interpretation.

## Next gate

The next scientific descriptor is **genesis relative to 850-hPa low-level inflow**. Its coordinate system is intentionally independent from the parent-motion coordinate system:

- positive along-inflow displacement = genesis on the meteorological wind-FROM / upstream side;
- negative along-inflow displacement = genesis on the downwind side.

Only after historical reconstruction will we test whether repeated upstream-side core genesis, persistence, weak translation, or combinations thereof carry incremental information about linear stationary heavy-rain systems.

## Risk engine

**NOT ALLOWED.**
