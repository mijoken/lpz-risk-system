# Phase 1C GFS Scientific Decode Baseline — 2026-09-09

## Status

**Initial low-ambiguity GFS scientific decode proof: PASS**

GitHub Actions run `34328317939` successfully executed the complete Phase 0.5 / 1A / 1B chain and then downloaded a live NOAA/NCEP GFS 0.25-degree scientific subset, decoded it with ECMWF ecCodes, validated the expected pressure-level fields, and executed the first paper-derived diagnostics.

## Runtime proof

- GFS source: NOMADS primary `filter_gfs_0p25.pl`
- Model cycle used: `2026-09-09T00:00:00Z`
- Forecast hour: `f001`
- Valid time: `2026-09-09T01:00:00Z`
- Scientific subset HTTP status: `200`
- GRIB2 subset size: `831,846 bytes`
- Transfer latency in the proof run: `1,051 ms`
- ecCodes runtime: `2.48.2`
- Expected low-ambiguity fields: `21`
- Decoded GRIB messages in the subset: `36`
- Grid points per required field: `14,641`
- Required-field finite-value coverage: `100%` in this proof

The 21 required fields were:

- RH: 500, 700 hPa
- U/V: 600 hPa
- U/V: 850 hPa
- q/U/V: 1000, 975, 950, 925, 900 hPa

## Gates closed by this proof

```text
GRIB transport                              PASS
ECMWF ecCodes decode                       PASS
required GFS pressure fields present       PASS
required fields finite                     PASS
required fields grid-compatible            PASS
Kato RH500/RH700 threshold calculation     PASS
600-hPa wind field decode                  PASS
850-hPa wind field decode                  PASS
Tahara 1000–900-hPa q/u/v raw stack       PASS
```

## Gates deliberately still closed

```text
Tahara IWVF pressure integral              PENDING
Tahara IWVF horizontal divergence          PENDING
Kato exact 500-m FLWV                      BLOCKED
Kato dLFC                                  PENDING
Kato EL                                    PENDING
Kato SREH 0–3 km                           PENDING
Kato 700-hPa geometric upward velocity     PENDING
Radar precipitation scientific decode      PENDING
Rainband object extraction                 PENDING
Historical reconstruction                  NOT STARTED
Risk engine                                DISABLED
```

These are not failures. They are scientific guardrails against silently replacing the published quantity with an easier proxy.

## First paper-derived live calculation

For the proof frame, the Kato (2020) mid-level humidity condition was calculated directly from the decoded GFS pressure-level RH fields:

- valid grid points: `14,641`
- grid points with both RH500 > 60% and RH700 > 60%: `2,708`
- domain fraction satisfying both thresholds: `0.1849600437`

This domain-wide fraction is **not** an LPZ risk probability. The current Japan-domain run is only a scientific-decode proof. Operational research will evaluate local regions / candidate rainband environments instead of converting this country-scale fraction into a score.

## Wind-field proof

600 hPa:
- valid points: `14,641`
- mean speed over proof domain: `12.1458 m/s`
- maximum speed: `38.5092 m/s`
- circular mean meteorological FROM direction: `253.17°`

850 hPa:
- valid points: `14,641`
- mean speed over proof domain: `9.3466 m/s`
- maximum speed: `31.1904 m/s`
- circular mean meteorological FROM direction: `326.53°`

These domain means are transport/decode checks only. The future Shimamura orientation feature will compare the **local 600-hPa wind direction near an objectively detected rainband** with the radar-derived rainband major-axis angle.

## Tahara low-level moisture stack proof

The 1000/975/950/925/900 hPa q/u/v stack was successfully decoded on the same 14,641-point grid at all five pressure levels.

GFS `SPFH` is specific humidity. Tahara et al. (2026) define `q` in the IWVF equations as water-vapor mixing ratio, so LPZ-RISK explicitly converts:

`mixing_ratio = specific_humidity / (1 - specific_humidity)`

before any future exact IWVF reproduction.

The actual IWVF pressure integral is intentionally not executed yet. The published notation must be reconciled with the numerical pressure-integration direction/sign convention before the formula gate can be opened.

## Important methodological interpretation

`kato_midlevel_rh_exact = true` means the **published RH pressure-level threshold calculation itself** can be reproduced exactly from the decoded GFS variables and units. It does **not** mean the GFS forecast field is identical to the atmospheric dataset used in Kato (2020), nor that the threshold is automatically a valid operational predictor in this system.

Likewise, `wind_600hpa_exact` and `wind_850hpa_exact` mean the pressure-level U/V quantity is directly available and decoded without a proxy transformation. The paper-level compound feature may still require radar geometry, persistence, regional context, or historical validation.

## Failure that produced this baseline

The first Phase 1C implementation attempted to use NOMADS `pgrb2b` / `filter_gfs_0p25b.pl`. Current proof requests returned empty payloads for completed cycles. The system did not downgrade that to success. The route was audited against current NOMADS availability and changed to the already proven primary GFS 0.25-degree filter, which exposes the required RH/SPFH/UGRD/VGRD pressure-level fields.

The successful retry demonstrates why the project keeps acquisition, scientific decode, and feature validity as separate gates.

## Next implementation target

Proceed in parallel with:

1. **Radar Scientific Decoder / Object Engine**
   - recover scientifically defensible precipitation values from JMA radar tiles
   - reconstruct georeferenced raster
   - implement objective rainfall objects and morphology based on Hirockawa-family definitions

2. **GFS feature completion without proxies**
   - local/candidate-region RH fields
   - local 600-hPa wind for orientation comparison
   - time-series 850-hPa wind persistence for the Kyushu-specific diagnostic
   - resolve Tahara IWVF numerical integration convention before opening that formula gate

Risk fusion remains prohibited until historical reconstruction and frozen validation.
