# LPZ Risk System

Explainable real-time risk monitoring and research system for linear precipitation zones in Japan.

> **Research / experimental system.** This repository is not an official weather warning service and must not replace information issued by the Japan Meteorological Agency (JMA) or local authorities.

## Current phase

**Phase 1B — Scientific Evidence Engine**

Phase 0 data-source audit and Phase 0.5 live acquisition proof are complete. Phase 1A established the initial canonical data adapter, and Phase 1B now converts peer-reviewed LPZ literature into machine-readable formulas, thresholds, statistical findings, limitations, and evidence-driven input-variable requirements.

### Phase 0.5 mandatory payload gate

- JMA High-Resolution Precipitation Nowcast — **PASS**
- JMA analyzed precipitation / RASRF — **PASS**
- JMA AMeDAS — **PASS**
- NOAA/NCEP GFS 0.25° — **PASS**

Supplementary sources:
- JMA Himawari — metadata proof complete; scientific image/channel validation pending
- JMA WINDAS — stable machine acquisition route pending

The scheduled proof remains conservative at 30-minute cadence while availability and scientific-decode evidence accumulates.

## Current scientific gates

```text
mandatory transport                        PASS
AMeDAS station normalization               PASS
Scientific Evidence Registry               CI VALIDATED
Evidence -> variable requirements          CI VALIDATED
paper misuse / proxy guardrails            CI ENFORCED
radar pixel scientific decode              PENDING
GFS evidence-variable scientific decode    PENDING
historical feature reconstruction          NOT STARTED
risk engine allowed                        NO
```

No LPZ prediction score will be introduced until scientific decoding, feature reconstruction, and frozen historical validation gates are closed.

## Scientific Evidence Engine policy

**Evidence is not an operational gate.**

Published formulas and thresholds retain their original region, sample, dataset, spatial/temporal resolution, unit conventions, and limitations. A literature-derived diagnostic is not promoted into the LPZ score merely because it appeared in a paper.

The initial curated evidence set covers:
- Kato (2020): six favorable environmental conditions and formation mechanisms
- Hirockawa et al. (2020): objective heavy-rainfall object detection/classification
- Hirockawa & Kato (2022): improved linear-stationary identification procedures
- Kato (2005): Kyushu-specific 850-hPa southwesterly persistence
- Shimamura et al. (2025): 6,760-object RRJ-Conv climatology and 600-hPa orientation relationship
- Hayashi et al. (2025): object-based forecast verification / Interest Value / SCS
- Kumagai et al. (2026): Tohoku rainfall-threshold sensitivity
- Tahara et al. (2026): northern-Japan 64-year climatology and 1000–900-hPa integrated water-vapor-flux diagnostics

Two critical guardrails are already enforced by tests and CI:
1. Kato's 500-m water-vapor-flux diagnostic is **not** silently replaced by a 950-hPa GFS proxy.
2. The six favorable conditions are treated as multi-evidence diagnostics, **not** a deterministic all-six event gate.

See:
- `research/evidence/scientific_evidence_registry.json`
- `config/scientific_variable_requirements.json`
- `docs/architecture/SCIENTIFIC_EVIDENCE_ENGINE.md`

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
Scientific literature
        |
        v
Scientific Evidence Registry
        |
        +--> formulas / thresholds / findings
        +--> scope / limitations
        +--> required weather variables
        |
        v
Evidence-aware acquisition requirements
        |
        +-------------------------------+
        |                               |
        v                               v
Public weather data              Historical sources
        |                               |
        v                               v
GitHub Actions               Historical reconstruction
        |                               |
        v                               |
Acquisition + validation               |
        |                               |
        v                               |
Canonical adapters <-------------------+
        |
        v
Future Scientific Feature Engine
        |
        v
Frozen validation / holdout
        |
        v
Only then: LPZ risk fusion
        |
        v
JSON / GeoJSON -> GitHub Pages dashboard
```

Live and historical pipelines remain intentionally separated. They converge at canonical variable and scientific feature definitions.

## Current evidence

The Phase 1A GitHub Actions proof normalized 1,286 AMeDAS stations, including 915 stations with wind observations and 841 with humidity observations. Station latitude/longitude metadata and meteorological wind vectors are normalized into the canonical schema.

GFS transport proof includes automatic fallback to the previous completed model cycle when a newly scheduled cycle is not yet published.

The Phase 1B registry drives GFS requirements from reproducible literature needs rather than collecting variables merely because they are available. It explicitly tracks exact reproduction, pending transformations, and blocked approximations.

See:
- `docs/PHASE0_DATA_SOURCE_AUDIT.md`
- `research/phase0/PHASE0_5_BASELINE_20260909.md`
- `research/phase1/PHASE1B_SCIENTIFIC_EVIDENCE_BASELINE_20260909.md`

## Run locally

```bash
python scripts/validate_scientific_evidence.py \
  --registry research/evidence/scientific_evidence_registry.json \
  --requirements config/scientific_variable_requirements.json \
  --output reports/evidence/scientific_evidence_validation.json

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
