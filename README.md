# LPZ Risk System

Explainable real-time risk monitoring and research system for linear precipitation zones in Japan.

> **Research / experimental system.** This repository is not an official weather warning service and must not replace information issued by the Japan Meteorological Agency (JMA) or local authorities.

## Current phase

**Phase 1C — Scientific Feature Engine**

Phase 0 data-source audit, Phase 0.5 live acquisition proof, Phase 1A canonical adapters, and the initial Phase 1B Scientific Evidence Engine are complete. Phase 1C is now reproducing paper-derived scientific quantities from live weather data under explicit exactness/proxy guardrails.

### Phase 0.5 mandatory payload gate

- JMA High-Resolution Precipitation Nowcast — **PASS**
- JMA analyzed precipitation / RASRF — **PASS**
- JMA AMeDAS — **PASS**
- NOAA/NCEP GFS 0.25° — **PASS**

Supplementary sources:
- JMA Himawari — metadata proof complete; scientific image/channel validation pending
- JMA WINDAS — stable machine acquisition route pending

The scheduled proof remains conservative at 30-minute cadence while scientific-decode and failure-behavior evidence accumulates.

## Current scientific gates

```text
mandatory transport                         PASS
AMeDAS station normalization                PASS
Scientific Evidence Registry                CI VALIDATED
Evidence -> variable requirements           CI VALIDATED
paper misuse / proxy guardrails             CI ENFORCED
ECMWF ecCodes runtime                       PASS
GFS low-ambiguity 21-field decode           PASS
Kato RH500/RH700 calculation                PASS
600-hPa U/V wind decode                     PASS
850-hPa U/V wind decode                     PASS
Tahara 1000–900-hPa q/u/v raw stack        PASS
Tahara IWVF formula                         PENDING
Kato exact 500-m FLWV                       BLOCKED
Kato SREH / LFC / EL / W700                 PENDING
radar pixel scientific decode               PENDING
rainband object extraction                  PENDING
historical feature reconstruction           NOT STARTED
risk engine allowed                         NO
```

No LPZ prediction score will be introduced until scientific decoding, historical reconstruction, and frozen validation gates are closed.

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

Critical guardrails enforced by tests and CI include:
1. Kato's 500-m water-vapor-flux diagnostic is **not** silently replaced by a 950-hPa GFS proxy.
2. The six favorable conditions are treated as multi-evidence diagnostics, **not** a deterministic all-six event gate.
3. GFS precomputed helicity is **not** assumed to be the same SREH construction used by Kato.
4. GFS pressure vertical velocity is **not** compared directly with Kato's geometric upward-velocity threshold before conversion and sign validation.
5. Tahara's IWVF input stack can be decoded, but the pressure-integral formula remains closed until its numerical sign/integration convention is explicitly verified.

See:
- `research/evidence/scientific_evidence_registry.json`
- `config/scientific_variable_requirements.json`
- `docs/architecture/SCIENTIFIC_EVIDENCE_ENGINE.md`

## Phase 1C live scientific proof

GitHub Actions has successfully downloaded and decoded a live evidence-driven GFS subset using ECMWF ecCodes.

Initial low-ambiguity proof fields:
- RH at 500 and 700 hPa
- U/V wind at 600 hPa
- U/V wind at 850 hPa
- specific humidity and U/V wind at 1000/975/950/925/900 hPa

The proof contained all 21 expected fields on a common 14,641-point Japan-domain grid, with finite values in every required field. The first Kato RH500/RH700 threshold calculation and the raw Tahara low-level moisture stack were executed successfully.

These are scientific feature/decode proofs, **not probabilities of LPZ occurrence**.

See `research/phase1/PHASE1C_GFS_SCIENTIFIC_DECODE_BASELINE_20260909.md`.

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
Scientific Feature Engine
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

The Phase 1A GitHub Actions proof normalized 1,286 AMeDAS stations, with roughly 915 stations carrying wind observations and roughly 840+ carrying humidity depending on the current observation frame. Station latitude/longitude metadata and meteorological wind vectors are normalized into the canonical schema.

GFS transport proof includes automatic fallback to a previous completed model cycle when a newly scheduled cycle is not yet published.

The Phase 1B registry drives GFS requirements from reproducible literature needs rather than collecting variables merely because they are available. Phase 1C then attempts live reproduction while keeping blocked transformations blocked.

See:
- `docs/PHASE0_DATA_SOURCE_AUDIT.md`
- `research/phase0/PHASE0_5_BASELINE_20260909.md`
- `research/phase1/PHASE1B_SCIENTIFIC_EVIDENCE_BASELINE_20260909.md`
- `research/phase1/PHASE1C_GFS_SCIENTIFIC_DECODE_BASELINE_20260909.md`

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

python scripts/gfs_scientific_decode_probe.py \
  --output reports/scientific/gfs_scientific_decode.json
```

No paid API or LLM API is required for the current phase.

## Repository policy

GitHub is the canonical source for code, configuration, research notes, schemas, workflows, and generated small JSON products. Large raw weather datasets are not committed to Git.

## Data freshness

The future operational dashboard will display observation time, analysis time, data age, and a `FRESH / STALE` status. If mandatory upstream data are stale, the current risk score must be suspended rather than silently reused.

## License

No project license has been selected yet. Third-party/public datasets remain subject to their own terms and attribution requirements.
