# C-2 JMA Public PNG × IMERG Early V07 Comparison Freeze

Date: 2026-09-17

## Status

PASS — research-only structural comparison completed.

This evidence does NOT authorize risk-engine or production integration.

## Scientific boundary

JMA public precipitation PNG is treated only as an interval-valued
categorical display product.

No class midpoint is invented.
No exact continuous JMA mm/h value is reconstructed.
No averaging of JMA class indices is interpreted as rainfall.
Transparent pixels are not silently converted to zero rainfall.

IMERG Early V07 is treated as a native 0.1-degree half-hour mean
rain-rate product.

No IMERG spatial interpolation or upsampling is used for the
scientific comparison.

Direct continuous-rate comparison between JMA public PNG and IMERG
remains blocked.

## Frozen JMA precipitation classes

P00_01  [0,1) mm/h
P01_05  [1,5) mm/h
P05_10  [5,10) mm/h
P10_20  [10,20) mm/h
P20_30  [20,30) mm/h
P30_50  [30,50) mm/h
P50_80  [50,80) mm/h
P80_INF [80,+inf) mm/h

These definitions reuse the Phase 1C radar scientific baseline.

## C-2A JMA raw capture

Support:
2026-09-17 04:05–04:35 UTC

Cadence:
5 minutes

Frames:
7

Tiles per frame:
49

Expected downloads:
343

Successful downloads:
343

Failed downloads:
0

Role:
RESEARCH_ONLY_TEMPORARY_JMA_RAW_CAPTURE

## C-2B IMERG target granules

Product:
GPM_3IMERGHHE V07 — IMERG Early

Granules:

1.
2026-09-17 04:00–04:30 UTC

3B-HHR-E.MS.MRG.3IMERG.20260917-S040000-E042959.0240.V07C.HDF5

SHA256:
8ea11d9037529d177130497bcf82b065d9ab38aa4c79a9722f4e14274c99ce8c

2.
2026-09-17 04:30–05:00 UTC

3B-HHR-E.MS.MRG.3IMERG.20260917-S043000-E045959.0270.V07C.HDF5

SHA256:
134c7e378052002ed3ad473a3fd6254fc38c3fb73985891b58bf39acc7245c1f

## IMERG structural proof

Grid/precipitation native shape:
[time, lon, lat]

Canonical project shape:
[lat, lon]

Resolution:
approximately 0.1 degree

Units:
mm/hr

Temporal support:
half-hour

Processing system observed:
PPS-NRT

The C-2 input is IMERG Early, not IMERG Final.

## Provenance correction

A concrete provenance bug was found during C-2.

The existing Final V07 decoder could numerically decode the Early HDF5
structure, but returned Final-product metadata:

source_id = NASA_IMERG_FINAL_V07
gauge_adjusted = True

The decoder was refactored to share one common V07 HDF5 decode path
while exposing separate provenance wrappers.

Final:

source_id = NASA_IMERG_FINAL_V07
gauge_adjusted = True

Early:

source_id = NASA_IMERG_EARLY_V07
gauge_adjusted = False

The C-2C-16 numerical regression was unchanged after switching to the
Early wrapper.

## C-2C-16 pixel-level connection proof

JMA frame:
2026-09-17 04:05 UTC

IMERG support:
2026-09-17 04:00–04:30 UTC

Classified JMA pixels:
15196

Comparable pixels:
15196

Unknown opaque JMA pixels:
0

Exact class agreement:
0.4894051066070018

Within-one-class agreement:
0.8843116609634114

This result is descriptive only because many JMA pixels map to the
same native IMERG cell.

## C-2C-17 native IMERG-cell comparison

Comparison unit:
one native IMERG 0.1-degree cell

Comparable IMERG cells:
1307

JMA pixels per IMERG cell:
minimum 1
median 8
maximum 35

JMA modal-class exact agreement:
0.6021423106350421

JMA modal-class within-one-class agreement:
0.9441469013006886

Threshold summary:

>=1 mm/h
JMA any = 0.65493497
JMA majority = 0.52027544
IMERG = 0.23871461

>=5 mm/h
JMA any = 0.25019128
JMA majority = 0.10711553
IMERG = 0.01759755

>=10 mm/h
JMA any = 0.15837796
JMA majority = 0.04131599
IMERG = 0.00459067

>=20 mm/h
JMA any = 0.08263198
JMA majority = 0.01224178
IMERG = 0

>=30 mm/h
JMA any = 0.04667177
JMA majority = 0.00306044
IMERG = 0

>=50 mm/h
JMA any = 0.02295333
JMA majority = 0
IMERG = 0

>=80 mm/h
JMA any = 0.00612089
JMA majority = 0
IMERG = 0

## C-2C-18 six-frame persistence proof

JMA frames:

04:05
04:10
04:15
04:20
04:25
04:30 UTC

IMERG:
04:00–04:30 UTC half-hour product

Union comparable IMERG cells:
1959

Threshold results:

>=1 mm/h
JMA any frame = 0.68861664
temporal persistence any = 0.56570529
mean spatial occupancy = 0.39764822
IMERG half-hour class = 0.18325676

>=5 mm/h
JMA any frame = 0.30321593
temporal persistence any = 0.19168794
mean spatial occupancy = 0.08499182
IMERG half-hour class = 0.01531394

>=10 mm/h
JMA any frame = 0.20265442
temporal persistence any = 0.12225625
mean spatial occupancy = 0.04561947
IMERG half-hour class = 0.00306279

>=20 mm/h
JMA any frame = 0.11638591
temporal persistence any = 0.05951166
mean spatial occupancy = 0.01598687
IMERG half-hour class = 0

>=30 mm/h
JMA any frame = 0.06380807
temporal persistence any = 0.03021950
mean spatial occupancy = 0.00662432
IMERG half-hour class = 0

>=50 mm/h
JMA any frame = 0.02807555
temporal persistence any = 0.01218309
mean spatial occupancy = 0.00194715
IMERG half-hour class = 0

>=80 mm/h
JMA any frame = 0.01225115
temporal persistence any = 0.00425387
mean spatial occupancy = 0.00052860
IMERG half-hour class = 0

## Interpretation

For this case, strong precipitation represented in the JMA public PNG
is spatially localized and becomes increasingly temporally sparse at
higher intensity thresholds.

The observed difference from IMERG is compatible with differences in
spatial and temporal support:

JMA public PNG:
high-resolution interval-valued instantaneous-intensity display

IMERG Early:
0.1-degree half-hour mean rain rate

This case does NOT establish that either source is more accurate.

It does NOT establish a general climatological relationship between
JMA and IMERG.

## Important limitation

C-2C-18 uses the union of cells represented across the six JMA frames.

A cell may therefore have fewer than six valid JMA observations.

Future formal validation should include a sensitivity analysis limited
to cells with complete 6/6-frame support.

This limitation does not invalidate the C-2 structural proof.

## Frozen gate

JMA public PNG class decoding        PASS
IMERG Early provenance              PASS
continuous -> frozen JMA class      PASS
real-data spatial connection        PASS
native-cell comparison              PASS
six-frame persistence               PASS

direct continuous JMA/IMERG rate    BLOCKED
JMA midpoint fabrication            FORBIDDEN
JMA class-index rainfall averaging  FORBIDDEN
IMERG spatial upsampling            NOT USED

generalization beyond this case     NOT ESTABLISHED
risk engine allowed                 NO
production integration allowed      NO

## Research disposition

C-2 is CLOSED as a structural proof.

Do not continue repeatedly analyzing this same event unless a concrete
scientific question requires it.

Next work should move to broader evidence / multi-event validation
rather than extracting additional statistics from this single case.
