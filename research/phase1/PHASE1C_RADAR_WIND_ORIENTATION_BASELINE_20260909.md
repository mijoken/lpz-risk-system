# Phase 1C Radar–600 hPa Wind Orientation Baseline — 2026-09-09

## Status

**PASS — live radar-object versus local GFS 600-hPa wind orientation comparison proven.**

Feature:

`rainband_vs_600hpa_wind_orientation`

Evidence link:

`SHIMAMURA2025_ORIENTATION600`

This baseline proves that the system can combine an observed precipitation-object major-axis orientation with a local, time-aligned 600-hPa GFS wind vector. It does **not** define an operational mismatch threshold and does not create an LPZ gate.

## Live proof

GitHub Actions run: **34333356981**

Radar valid time:

- `2026-09-09T08:55:00Z`

GFS selected by conservative time-alignment policy:

- cycle: `2026-09-09T00:00:00Z`
- forecast hour: `f009`
- forecast valid time: `2026-09-09T09:00:00Z`
- absolute valid-time mismatch: **5 minutes**
- transport: HTTP 200
- subset bytes: 822,696

The model-cycle policy requires the GFS cycle to be at least four hours older than the radar valid time. This is a conservative first guard against historical data-availability leakage; exact archive/publication-time reconstruction remains required before frozen historical validation.

## Comparison convention

Rain-object orientation is an undirected line axis with 180-degree symmetry.
Meteorological wind direction is a 360-degree FROM direction.

For comparison:

1. Wind direction is reduced to an undirected axis modulo 180.
2. Rain orientation is also normalized modulo 180.
3. Mismatch is the acute axis difference in `[0, 90]` degrees.

This means a 20° wind FROM direction and a 200° wind FROM direction represent the same environmental axis for the purpose of rainband-orientation alignment.

## Live results

Total radar-object / local-wind comparisons: **39**.

### Largest untruncated object

- threshold: >=30 mm/h
- area: 154.883 km²
- aspect ratio: 1.591
- centroid: 144.0754°E, 37.8321°N
- rain-object axis: 83.200°
- nearest GFS grid: 144.00°E, 37.75°N
- local 600-hPa wind U: 24.346 m/s
- local 600-hPa wind V: 11.569 m/s
- local wind speed: 26.955 m/s
- meteorological FROM direction: 244.584°
- wind axis: 64.584°
- acute axis mismatch: **18.616°**

### Most elongated untruncated object

- threshold: >=30 mm/h
- area: 24.535 km²
- aspect ratio: **3.433**
- centroid: 142.6379°E, 38.4566°N
- rain-object axis: 40.541°
- nearest GFS grid: 142.75°E, 38.50°N
- local 600-hPa wind speed: 27.435 m/s
- meteorological FROM direction: 247.772°
- wind axis: 67.772°
- acute axis mismatch: **27.231°**

These values are observations from one live proof. They are not evidence that 18°, 27°, or any other mismatch is predictive of LPZ formation.

## Guardrails

- no alignment threshold is hard-coded
- no alignment score enters a risk engine
- nearest local GFS grid point is logged explicitly
- radar and GFS valid times are logged explicitly
- GFS cycle age policy is logged explicitly
- boundary-truncated radar objects remain distinguishable
- orientation comparison is separated from Hirockawa HRA / official LPZ definitions

## Scientific gates after this baseline

```text
radar public-PNG class decode                PASS
radar live object morphology                PASS
600-hPa wind decode                         PASS
local 600-hPa wind sampling                 PASS
radar-vs-wind axial mismatch                PASS
historical orientation distribution         NOT STARTED
incremental predictive-value test           NOT STARTED
multi-frame object tracking                 NEXT
stationarity / overlap                      NEXT
back-building proxy                         NEXT
risk engine allowed                         NO
```

## Next step

Build the multi-frame precipitation-object tracker. The tracker must connect objects across successive 5-minute radar frames and preserve:

- object identity / lineage
- centroid displacement
- motion vector and speed
- area and intensity-class evolution
- orientation evolution
- overlap ratio
- split / merge events
- new-cell genesis upstream of an existing object

Only after this temporal layer exists can the system test stationarity, persistence, and back-building evidence without confusing a single elongated snapshot with a quasi-stationary rainband.
