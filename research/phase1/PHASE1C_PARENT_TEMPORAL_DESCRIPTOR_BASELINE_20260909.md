# Phase 1C Parent Temporal Descriptor Baseline — 2026-09-09

## Status

**PASS — deterministic parent-lineage temporal descriptors derived from the frozen Run 47 tracking/hierarchy evidence.**

Feature: `parent_precipitation_temporal_descriptors_public_png`

No stationarity or back-building class is defined. The purpose is to preserve independent temporal dimensions for historical analysis.

## Source evidence

Derived from GitHub Actions run **34334423235**:
- `radar_tracking.json`
- `radar_hierarchy.json`

Descriptor implementation:
- `src/lpz_risk/radar_temporal.py`
- `scripts/radar_temporal_descriptor.py`

## Descriptor fields

Each >=30 mm/h parent lineage stores:
- frame count / observed duration
- first and last centroid
- net centroid displacement
- matched path displacement
- mean / median / maximum centroid speed
- median IoU
- mean previous/current overlap fractions
- mean / min / max area
- area change
- any boundary truncation
- frames containing >=50 mm/h embedded cores
- frames containing >=80 mm/h embedded cores
- >=50 / >=80 embedded-core genesis counts

These are long-form explanatory variables, not score components.

## Most informative live lineages

### T30-L0016

- observed duration: **15 min**
- frames: 4/4
- net displacement: **22.87 km**
- matched path displacement: **22.83 km**
- median speed: **24.27 m/s**
- median IoU: **0.240**
- mean area: **159.68 km²**
- maximum area: **209.55 km²**
- frames with >=50 core: **4/4**
- frames with >=80 core: **4/4**
- new >=50 cores inside existing parent: **3**
- new >=80 cores inside existing parent: **5**
- total embedded-core genesis: **8**
- boundary truncated: false

Interpretation: very active embedded-core production, but also rapid translation. It must not be described as stationary from this sample.

### T30-L0008

- duration: **15 min**
- net displacement: **17.69 km**
- path displacement: **19.59 km**
- median speed: **21.44 m/s**
- median IoU: **0.094**
- mean area: **94.81 km²**
- maximum area: **132.62 km²**
- frames with >=50 core: 3/4
- frames with >=80 core: 2/4
- embedded-core genesis: **5**
- boundary truncated: false

### T30-L0042

- duration: **15 min**
- net displacement: **7.29 km**
- path displacement: **8.68 km**
- median speed: **10.44 m/s**
- median IoU: **0.228**
- mean area: **112.07 km²**
- maximum area: **315.35 km²**
- frames with >=50 core: 4/4
- frames with >=80 core: 3/4
- embedded-core genesis: **4**
- boundary truncated: **true**

Because this lineage touches the sampled mosaic boundary, its area/motion descriptors require caution and it must not be favored simply because its displacement is smaller.

### T30-L0031

- duration: **15 min**
- net displacement: **20.24 km**
- path displacement: **20.25 km**
- median speed: **23.04 m/s**
- median IoU: **0.099**
- mean area: **41.23 km²**
- maximum area: **47.40 km²**
- >=50 core present: 4/4 frames
- >=80 core present: 0/4 frames
- embedded >=50 genesis: **3**

## Key scientific consequence

The live sample already demonstrates that two potentially important ideas are independent:

1. **core-generation activity** — repeated creation of stronger precipitation cores inside a broader parent;
2. **stationarity** — limited translation / persistent spatial occupation of the broader parent.

For example, T30-L0016 had the highest core-genesis count but translated ~23 km in only 15 minutes. A future model must not collapse these dimensions into a single hand-written "back-building/stationary" score before historical validation.

## Next step

For every embedded-core genesis event, calculate its position relative to the parent motion vector:

- along-motion offset (km)
- cross-motion offset (km)
- parent motion speed/direction
- whether the along-motion offset is negative or positive

A negative along-motion offset is only a geometric statement (behind the translating parent), not yet a meteorological `back-building=true` label.

Future work will additionally compare genesis position with low-level environmental inflow/wind before any back-building classification is considered.

## Gates

```text
parent temporal long-form descriptor         PASS
core-generation vs translation separation   PASS
stationarity threshold                      NONE
back-building threshold                     NONE
genesis relative-motion geometry            NEXT
historical validation                       NOT STARTED
risk engine allowed                         NO
```
