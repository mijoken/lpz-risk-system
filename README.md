# LPZ Risk System

Explainable real-time risk monitoring and research system for linear precipitation zones in Japan.

> **Research / experimental system.** This repository is not an official weather warning service and must not replace information issued by the Japan Meteorological Agency (JMA) or local authorities.

## Current phase

**Phase 1A — Canonical Data Adapter Proof**

Phase 0 data-source audit is complete and Phase 0.5 has demonstrated real payload acquisition for all four mandatory sources from GitHub Actions.

### Phase 0.5 mandatory payload gate

- JMA High-Resolution Precipitation Nowcast — **PASS**
- JMA analyzed precipitation / RASRF — **PASS**
- JMA AMeDAS — **PASS**
- NOAA/NCEP GFS 0.25° — **PASS**

Supplementary sources:
- JMA Himawari — metadata proof complete; scientific image/channel validation pending
- JMA WINDAS — stable machine acquisition route pending

The scheduled proof remains conservative at 30-minute cadence while availability and freshness evidence accumulates.

## Current Phase 1A gates

```text
mandatory transport              PASS
AMeDAS station normalization     PASS
radar pixel scientific decode    PENDING
GFS LPZ-variable decode          PENDING
risk engine allowed              NO
```

No LPZ prediction score will be introduced until the scientific decoding gates are closed.

## v0.1 source policy

**Live mandatory**
- JMA High-Resolution Precipitation Nowcast
- JMA analyzed precipitation / RASRF
- JMA AMeDAS
- NOAA/NCEP GFS 0.25°

**Live supplementary**
- JMA WINDAS / wind profiler
- JMA Himawari imagery

**Benchmark only — never an input to the independent LPZ score**
- JMA official linear precipitation zone detection / event records
- JMA LPZ short-range prediction products

**Hazard overlay only**
- JMA Kikikuru products

**Historical core**
- ERA5
- JMA official LPZ event records
- historical radar where legally and technically available

**Research / future upgrade**
- DIAS XRAIN
- JAXA P-Tree
- GEONET-derived PWV
- JMA LFM / 30-minute atmospheric analysis / ensemble products

## Architecture

```text
Public weather data
        |
        v
GitHub Actions
        |
        v
Acquisition + validation
        |
        v
Canonical adapters
  - source_health
  - radar_frame
  - surface_station_frame
  - environment_frame
        |
        +--> historical research / backtest
        |
        v
Future LPZ state / risk engine
        |
        v
JSON / GeoJSON
        |
        v
GitHub Pages dashboard
```

Live and historical pipelines are intentionally separated. They converge only at canonical feature definitions.

## Current evidence

The Phase 1A GitHub Actions proof normalized 1,286 AMeDAS stations, including 915 stations with wind observations and 841 with humidity observations. Station latitude/longitude metadata and meteorological wind vectors are normalized into the canonical schema.

GFS transport proof includes automatic fallback to the previous completed model cycle when a newly scheduled cycle is not yet published.

See:
- `docs/PHASE0_DATA_SOURCE_AUDIT.md`
- `research/phase0/PHASE0_5_BASELINE_20260909.md`

## Run locally

```bash
python scripts/acquisition_probe.py \
  --output reports/acquisition/acquisition_report.json

python scripts/build_canonical_snapshot.py \
  --acquisition-report reports/acquisition/acquisition_report.json \
  --output reports/canonical/canonical_snapshot.json
```

No paid API or LLM API is required for the current phase.

## Repository policy

GitHub is the canonical source for code, configuration, research notes, schemas, workflows, and generated small JSON products. Large raw weather datasets are not committed to Git.

## Data freshness

The future operational dashboard will display observation time, analysis time, data age, and a `FRESH / STALE` status. If mandatory upstream data are stale, the current risk score must be suspended rather than silently reused.

## License

No project license has been selected yet. Third-party/public datasets remain subject to their own terms and attribution requirements.
