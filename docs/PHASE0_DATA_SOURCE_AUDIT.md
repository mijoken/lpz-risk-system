# Phase 0 — Data Source Audit

Status: **GO to Phase 0.5 Data Acquisition Proof**

This document records the source-selection policy. It is deliberately separate from the future prediction model.

## Design principle

The system does not attempt to duplicate JMA's numerical weather prediction stack. It independently estimates formation risk from public observational/model data and later compares its output with official JMA products.

## Frozen v0.1 categories

| Source | Role | Initial acquisition proof |
|---|---|---|
| JMA High-Resolution Precipitation Nowcast | LIVE_MANDATORY | metadata + sample PNG tile |
| JMA analyzed precipitation / rasrf | LIVE_MANDATORY | metadata first; raster next |
| JMA AMeDAS | LIVE_MANDATORY | actual JSON payload |
| NOAA/NCEP GFS 0.25° | LIVE_MANDATORY | service first; Japan GRIB2 subset next |
| JMA WINDAS | LIVE_SUPPLEMENTARY | endpoint discovery pending |
| JMA Himawari | LIVE_SUPPLEMENTARY | metadata first; imagery/channel proof next |
| JMA official LPZ products | BENCHMARK_ONLY | never predictor input |
| JMA Kikikuru | HAZARD_OVERLAY_ONLY | never predictor input |
| ERA5 | HISTORICAL_CORE | Phase 1/2 |
| DIAS XRAIN | RESEARCH_PRIORITY | application / access path |
| GEONET PWV | RESEARCH_OPTIONAL | later moisture study |
| JMA LFM / 30-min atmospheric analysis | FUTURE_UPGRADE | paid/official delivery route |

## Why official LPZ predictions are isolated

Using an official LPZ forecast as a predictor and then comparing the system against that same official forecast would contaminate the benchmark. Official JMA LPZ forecasts therefore remain outside the independent predictor pipeline.

## Live vs historical separation

The acquisition URL or file format does not need to be identical between live operation and historical reconstruction. Each source is converted to a canonical feature definition.

```text
LIVE JMA radar PNG ──────┐
                         ├──> canonical rain_intensity / cell objects
HISTORICAL XRAIN data ───┘
```

This allows historical research to use the best legally obtainable archive without coupling the operational system to the same distributor.

## Phase 0.5 gates

A mandatory source must eventually satisfy all of these:

1. Actual scientific payload download succeeds from GitHub Actions.
2. Payload parse succeeds.
3. Observation/valid time is recoverable.
4. Freshness can be computed.
5. Download size and latency are recorded.
6. Repeated runs show acceptable availability.
7. Failure does not silently reuse stale data.
8. Data-use terms and attribution are documented.

`METADATA` and `SERVICE` probes are intermediate states, not final acceptance.

## Primary references

- JMA Weather Data Guide: https://www.data.jma.go.jp/developer/weatherdataguide/
- JMA High-Resolution Precipitation Nowcast guide: https://www.data.jma.go.jp/developer/weatherdataguide/appendix/2-1-b.html
- JMA AMeDAS guide: https://www.data.jma.go.jp/developer/weatherdataguide/appendix/1-1-a.html
- JMA wind profiler guide: https://www.data.jma.go.jp/developer/weatherdataguide/appendix/1-2-a.html
- JMA Himawari guide: https://www.data.jma.go.jp/developer/weatherdataguide/appendix/1-5-a.html
- NOAA NOMADS GFS grib filter: https://nomads.ncep.noaa.gov/gribfilter.php?ds=gfs_0p25

URLs used by the probe are treated as implementation dependencies and must be monitored for upstream changes.
