# Phase 2C Official Primary-Subdivision Polygon Baseline

Date: 2026-09-10 JST

## Status

Official JMA primary-subdivision polygon geometry is now reproducibly derived in GitHub Actions for every subdivision code used by the current positive-anchor population.

- Required primary-subdivision codes: 58
- Resolved official polygon features: 58
- Missing codes: 0
- Source authority: Japan Meteorological Agency
- Source archive: `20190125_AreaForecastLocalM_1saibun_GIS.zip`
- Source CRS: JGD2011 geographic lon/lat
- Source archive committed to GitHub: no
- Derived GeoJSON: yes, generated as CI evidence
- Spatial Proof Run: GitHub Actions Run 34372055460
- Spatial Proof result: PASS
- Risk Engine: OFF

## Geometry semantics

The derived GeoJSON preserves official Polygon/MultiPolygon parts. Where one subdivision code is represented by multiple official shape records, those geometries are retained as a GeoJSON GeometryCollection rather than dissolved or approximated by a bounding box.

Historical rainfall masking semantics are frozen as:

`GRID_CELL_CENTRE_INSIDE_OFFICIAL_POLYGON`

The existing bbox registry remains valid only for ERA5 request subsetting. It must not be substituted for the official polygon when calculating subdivision-specific rainfall area.

## Raster-mask utilities

`src/lpz_risk/historical_polygon.py` now provides:

- Polygon / MultiPolygon / GeometryCollection point inclusion
- hole exclusion
- 2-D grid-centre masking
- regular lat/lon cell-area calculation using spherical cell geometry
- rainfall/mask/area-grid consistency validation

Nominal `1 km` analyzed-rainfall cells are not assumed to have exactly 1.0 km² area. Once a real historical analyzed-rainfall payload is decoded, the actual coordinate centres / grid definition must drive the cell-area grid.

If the DVD GPV grid is not a separable regular latitude/longitude grid, the generic spherical regular-grid area routine must not be forced onto it; a payload-specific area routine must be implemented after the format audit.

## Historical analyzed-rainfall source finding

The JMBSC `解析雨量サンプル` link is a display image, not a downloadable sample GPV payload. It therefore cannot be used as a decoder proof.

JMBSC documents the offline analyzed-rainfall media as daily GPV files with run-length compression and states that media from 1999 onward include a C-language decode program. For 2014 onward, the offline analyzed-rainfall data are reanalysed after the fact so that late-arriving observations can be incorporated; the data format itself was not changed by that reanalysis policy.

Accordingly, no speculative DVD GPV/RLE decoder will be written before an actual payload plus its bundled format documentation/decoder is available.

## Next external data gate

Obtain at least one actual JMBSC historical analyzed-rainfall annual payload, ideally beginning with one research year. The first payload audit must determine:

1. exact day-file naming and byte layout;
2. run-length encoding semantics;
3. missing / outside-domain codes;
4. precipitation scaling and units;
5. valid-time convention for each 30-minute record of previous-one-hour rainfall;
6. grid dimensions and coordinate mapping;
7. consistency with the bundled C decoder / format documentation;
8. whether polygon masking and latitude-aware area computation can be applied directly.

Until this gate passes:

- real hard-negative candidate generation remains blocked;
- final hard-negative labels remain forbidden;
- morphology-dependent historical features remain blocked;
- Risk Engine remains OFF.
