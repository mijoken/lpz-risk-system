# Phase 1C Radar Scientific Decode Baseline — 2026-09-09

## Status

**PASS — public JMA precipitation PNG class decoding is scientifically usable as an interval-valued display product.**

This baseline does **not** claim recovery of the native continuous radar/QPE field from website imagery and does **not** unlock the LPZ risk engine.

## Proven live pipeline

GitHub Actions run `34331741755` successfully executed:

```text
JMA targetTimes
    -> settled frame selection
    -> national z=6 discovery scan
    -> official precipitation RGB classification
    -> even-zoom Web-Mercator descendant verification
    -> z=8 verification
    -> z=10 verification
```

Both JMA High-Resolution Precipitation Nowcast (`hrpns`) and JMA analyzed precipitation (`rasrf`) passed.

## Official class semantics retained

The decoder stores precipitation as intervals only:

| Class | RGB | Interval (mm/h) |
|---|---|---:|
| P00_01 | 242,242,255 | [0,1) |
| P01_05 | 160,210,255 | [1,5) |
| P05_10 | 33,140,255 | [5,10) |
| P10_20 | 0,65,255 | [10,20) |
| P20_30 | 250,245,0 | [20,30) |
| P30_50 | 255,153,0 | [30,50) |
| P50_80 | 255,40,0 | [50,80) |
| P80_INF | 180,0,104 | [80,+inf) |

No midpoint is invented. For example, a P30_50 pixel is **not** converted to 40 mm/h.

Transparent pixels are not silently rewritten to 0 mm/h. Unknown opaque RGB values fail scientific palette integrity.

## Live evidence from the frozen proof

Proof timestamp: `2026-09-09T08:55:09Z`.

### Nowcast

Settled frame: `2026-09-09T08:40:00Z`.

- national z=6 discovery tiles: 49 / 49 fetched
- tiles containing precipitation: 14
- unknown opaque pixels: 0
- strongest detected class: P80_INF (>=80 mm/h)
- z=8: precipitation observed in 12 / 16 descendants
- z=10: precipitation observed in 13 / 16 descendants
- strongest z=10 seed: approximately 143.912E, 37.750N

### RASRF

Settled frame: `2026-09-09T08:40:00Z`.

- national z=6 discovery tiles: 49 / 49 fetched
- tiles containing precipitation: 15
- unknown opaque pixels: 0
- strongest detected class: P50_80 (50–80 mm/h)
- z=8: precipitation observed in 13 / 16 descendants
- z=10: precipitation observed in 14 / 16 descendants
- strongest z=10 seed: approximately 132.713E, 29.742N

## Tile-pyramid finding

During proof development, z=7 and z=9 repeatedly returned transparent placeholder tiles even when the same footprint had strong precipitation at z=6. Independent current-source implementation evidence reports the JMA precipitation tile pyramid as populated on even zooms (z=4, 6, 8, 10), with odd zooms returning transparent placeholders.

LPZ-RISK therefore treats odd-zoom transparency as a **tile-distribution property**, not as meteorological no-rain.

The operational/research code verifies populated even zooms only.

## Exactness boundary

### Proven

- PNG transport
- official precipitation-palette classification
- interval-valued precipitation class
- Web-Mercator tile/pixel geolocation
- approximate display-pixel ground area
- z=8 and z=10 live precipitation-colour availability

### Not proven / intentionally blocked

- exact continuous mm/h recovery from public PNG
- native 250-m radar/QPE grid reconstruction from display pixels
- exact 3-hour accumulation field from instantaneous display PNG
- exact Hirockawa HRA reproduction from public PNG alone
- operational LPZ probability or risk score

## Consequence for Scientific Feature Engine

Two radar paths are now formally separated:

```text
LIVE PUBLIC-PNG PATH
JMA display PNG
  -> interval classes
  -> live precipitation-object morphology
  -> line orientation / area / persistence / movement

EXACT HISTORICAL / NUMERIC PATH
numeric radar / analyzed precipitation / XRAIN / GRIB2 when available
  -> continuous or native quantitative field
  -> exact paper reproduction
  -> Hirockawa/Hayashi historical validation
```

The next Phase 1C task is `live_precip_object_morphology_public_png`:

- connected precipitation objects
- approximate ground area
- centroid
- major/minor axes
- aspect ratio
- orientation
- maximum precipitation class

It is explicitly **not** named `hirockawa_hra_exact`.

## Frozen gates after this baseline

```text
radar public PNG class decode           PASS
continuous radar mm/h recovery          BLOCKED
exact 3-h accumulation                  BLOCKED
live public-PNG morphology              NEXT
historical exact HRA reconstruction     NOT STARTED
risk engine allowed                     NO
```
