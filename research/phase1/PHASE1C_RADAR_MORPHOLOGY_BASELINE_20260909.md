# Phase 1C Radar Morphology Baseline — 2026-09-09

## Status

**PASS — live public-PNG precipitation-object morphology proven.**

This baseline freezes the first successful live extraction of precipitation-object geometry from JMA High-Resolution Precipitation Nowcast display PNG classes.

It is intentionally **not** a reproduction of Hirockawa heavy-rainfall areas (HRA). The public PNG contains discrete instantaneous precipitation-intensity classes; Hirockawa HRA requires continuous 3-hour accumulated precipitation plus temporal/object criteria.

## Frozen feature identity

`live_precip_object_morphology_public_png`

Exact public-palette thresholds used:

- 30 mm/h
- 50 mm/h
- 80 mm/h

Thresholds such as 40 mm/h are rejected because they fall inside a PNG interval and cannot be represented exactly without inventing continuous intensity.

## Live proof

GitHub Actions run: **34332929506**

Frame:

- basetime: `20260909085000`
- validtime: `20260909085000`
- valid time: `2026-09-09T08:50:00Z`

Discovery:

- z6 Japan tiles attempted: 49
- z6 tiles with precipitation: 14
- strongest class: `P80_INF`
- unknown opaque pixels: 0

z8 morphology mosaic:

- 16 contiguous descendant tiles (4 x 4)
- mosaic size: 1024 x 1024 pixels
- precipitation-classified pixels: 262,905
- maximum class: `P80_INF`
- unknown opaque pixels: 0

## Object results

| Exact threshold | Object count | Largest area km² | Major axis km | Minor axis km | Aspect ratio | Orientation ° | Boundary truncated |
|---:|---:|---:|---:|---:|---:|---:|---|
| >=30 mm/h | 42 | 126.525 | 18.022 | 11.699 | 1.541 | 91.514 | false |
| >=50 mm/h | 13 | 28.474 | 8.633 | 4.392 | 1.966 | 17.455 | false |
| >=80 mm/h | 2 | 10.036 | 6.099 | 2.342 | 2.604 | 9.186 | false |

The >=80 mm/h object having aspect ratio >2.5 is **not** evidence that the object is an LPZ. It is only an instantaneous high-intensity object whose PCA morphology is elongated. No 3-hour accumulation, minimum HRA area, overlap persistence, back-building, or official LPZ criterion is implied.

## Geometry definition

- segmentation: 8-connected components
- area: sum of latitude-adjusted Web-Mercator ground-pixel areas
- centroid: mean of member pixel-center longitude/latitude
- major/minor axes: PCA descriptors using `4 * sqrt(eigenvalue)`
- orientation: PCA major-axis bearing clockwise from north in `[0, 180)`
- aspect ratio: major axis / minor axis
- `boundary_truncated=true`: component touches the edge of the 4x4 z8 proof mosaic and may extend beyond the sampled region

These definitions are descriptive live-system features. They are not silently substituted for paper-specific object definitions.

## Tests / guardrails

The morphology test suite verifies:

1. 30/50/80 mm/h exact-boundary masks.
2. rejection of non-representable thresholds such as 40 mm/h.
3. 8-connected diagonal connectivity.
4. separation of disconnected objects.
5. east-west orientation recovery.
6. north-south orientation recovery.
7. mosaic-boundary truncation flagging.
8. minimum-pixel noise filtering.

All tests passed in CI before the live proof.

## Scientific gates after this baseline

```text
JMA public PNG class decode                 PASS
live precipitation-object segmentation     PASS
object area / centroid                     PASS
PCA major/minor axes                       PASS
aspect ratio / orientation                 PASS
boundary-truncation guard                  PASS
Hirockawa exact 3-h HRA                    BLOCKED
multi-frame persistence                    NOT YET IMPLEMENTED
600-hPa wind orientation consistency       NEXT
risk engine allowed                        NO
```

## Next step

Combine the observed rain-object major-axis orientation with already-decoded GFS 600-hPa U/V wind to produce a separate scientific feature:

`rainband_vs_600hpa_wind_orientation`

The feature will preserve both raw angles and their acute angular mismatch. It must not become an LPZ gate until historical reconstruction and frozen validation establish incremental predictive value.
