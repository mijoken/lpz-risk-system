# LPZ Risk System

Explainable real-time risk monitoring and research system for linear precipitation zones in Japan.

> **Research / experimental system.** This repository is not an official weather warning service and must not replace information issued by the Japan Meteorological Agency (JMA) or local authorities.

## Current phase

**Phase 0.5 — Data Acquisition Proof**

Before building any LPZ risk score, this phase verifies that the planned live data sources can actually be acquired and parsed reliably from GitHub Actions.

### v0.1 source policy

**Live mandatory**
- JMA High-Resolution Precipitation Nowcast
- JMA analyzed precipitation / precipitation-analysis metadata
- JMA AMeDAS
- NOAA/NCEP GFS 0.25°

**Live supplementary**
- JMA WINDAS / wind profiler
- JMA Himawari imagery metadata

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
        +--> raw/normalized data adapters
        |
        v
Canonical JSON / GeoJSON
        |
        +--> research / backtest
        |
        v
GitHub Pages dashboard
```

Live and historical pipelines are intentionally separated. They converge only at a canonical feature schema.

## Phase 0.5 acceptance policy

A source is not promoted to `CORE` merely because documentation says it exists. We collect evidence from repeated workflow runs and record:

- HTTP/download success
- payload parse success
- observation/valid time
- data age / freshness
- response bytes
- latency
- record count or metadata count
- failure details
- probe type (`PAYLOAD`, `METADATA`, `SERVICE`)
- promotion state

The first probe intentionally starts conservatively. Metadata-only success does **not** equal final payload acceptance.

## Run locally

```bash
python scripts/acquisition_probe.py --output reports/acquisition/acquisition_report.json
```

No paid API or LLM API is required for Phase 0.5.

## Repository policy

GitHub is the canonical source for code, configuration, research notes, schemas, workflows, and generated small JSON products. Large raw weather datasets are not committed to Git.

## Data freshness

The future operational dashboard will display observation time, analysis time, data age, and a `FRESH / STALE` status. If upstream data are stale, the current risk score must be suspended rather than silently reused.

## License

No project license has been selected yet. Third-party/public datasets remain subject to their own terms and attribution requirements.
