# Phase 1B Scientific Evidence Baseline — 2026-09-09

## Status

Initial Scientific Evidence Engine baseline established.

This baseline changes LPZ-RISK from a weather-variable-first project into an evidence-driven scientific reconstruction project. Weather variables are requested because they are needed to reproduce explicit peer-reviewed diagnostics, not merely because a data provider exposes them.

## Initial curated literature set

1. Kato (2005), JMSJ — Kyushu band-shaped rainfall systems
2. Kato (2020), JMSJ — Senjo-Kousuitai review and six favorable conditions
3. Hirockawa et al. (2020), JMSJ — objective HRA identification/classification
4. Hirockawa & Kato (2022), SOLA — improved linear-stationary identification
5. Shimamura et al. (2025), SOLA — RRJ-Conv 1976–2020 / 6,760 Senjo-Kousuitai objects
6. Hayashi et al. (2025), SOLA — object-based forecast verification, IV and SCS
7. Kumagai et al. (2026), SOLA — Tohoku rainfall-threshold sensitivity
8. Tahara et al. (2026), SOLA — northern Japan 1959–2022 / 361 line-shaped MCS events

## Baseline scientific findings incorporated

### Kato six favorable conditions

The registry separately stores:
- 500 m low-level water-vapor flux
- distance from 500 m to LFC
- 500/700 hPa relative humidity
- 0–3 km SREH
- large-scale 700 hPa ascent
- equilibrium-level height

Policy: these are separate diagnostics and may later form a count/coverage feature. They are not a deterministic all-six gate.

### 500 m water-vapor-flux exactness

Kato's diagnostic is defined at 500 m height. Current GFS pressure-level availability does not provide a 500 m AGL pressure-level equivalent. LPZ-RISK therefore blocks exact reproduction until a terrain-aware height interpolation from surrounding pressure levels is implemented and verified.

The project explicitly rejects the shortcut `500 m == 950 hPa` as an exact scientific reproduction.

### Objective rainfall-object morphology

Hirockawa-family methods provide reproducible object definitions involving:
- 3 h accumulated precipitation
- contiguous area
- local maximum rainfall
- aspect ratio
- object overlap
- persistence

These become targets for the future Radar Scientific Decoder / Object Engine, not hand-selected visual rules.

### 600 hPa rainband orientation relation

Shimamura et al. (2025) found the strongest environmental wind-direction relationship with rainband orientation at 600 hPa in the 6,760-object RRJ-Conv sample.

Planned reproducible feature:

`orientation_mismatch = circular_angle_difference(rainband_major_axis, wind_direction_600hPa)`

This requires both scientific radar-object orientation and GFS 600 hPa U/V decoding.

### Object-based forecast verification

Hayashi et al. (2025) supplies a framework to score forecast objects using multiple properties rather than only grid hit/miss. LPZ-RISK stores the preliminary Interest Value normalization components, matching criteria, and SCS formulation for later historical verification.

Policy: the 2024 normalization ranges are provisional and are not predictor thresholds.

### Regional threshold sensitivity

Kumagai et al. (2026) demonstrates that changing rainfall thresholds changes object composition itself. Regional detection is therefore treated as an object-regime problem, not a scalar threshold-tuning problem.

### Vertically integrated water-vapor flux

Tahara et al. (2026) supplies directly reproducible 1000–900 hPa diagnostics:

`IWVF = (1/g) * integral(q * V dp)`

and

`IWVF_div = (1/g) * integral[d(q*u)/dx + d(q*v)/dy] dp`.

LPZ-RISK will also store `moisture_flux_convergence = -IWVF_div` with sign convention made explicit.

Current GFS requirement stack retains all available 1000/975/950/925/900 hPa layers rather than using a single-layer proxy.

## Scientific quality-control decisions frozen in this baseline

1. A published threshold is evidence, not automatic operational truth.
2. Original region, sample, resolution, data source, units, and limitations are mandatory metadata.
3. Pressure-level proxies cannot be silently labelled exact height-level reproductions.
4. GFS `VVEL` (omega) cannot be compared directly with a geometric vertical velocity threshold without conversion and sign validation.
5. GFS precomputed helicity cannot be assumed identical to paper-specific SREH methodology.
6. National uniform rainfall thresholds will not be frozen before regional holdout testing.
7. JMA official LPZ prediction remains benchmark-only and does not enter the independent risk feature set.
8. Risk Engine remains disabled during Phase 1B/1C.

## Machine artifacts

- `research/evidence/scientific_evidence_registry.json`
- `config/scientific_variable_requirements.json`
- `src/lpz_risk/evidence.py`
- `scripts/validate_scientific_evidence.py`
- `tests/test_scientific_evidence.py`
- `docs/architecture/SCIENTIFIC_EVIDENCE_ENGINE.md`

## Gate state at baseline

```text
Mandatory live transport                   PASS
AMeDAS canonical normalization             PASS
Scientific Evidence Registry               VALIDATION REQUIRED BY CI
Evidence -> variable cross-reference       VALIDATION REQUIRED BY CI
Scientific misuse guardrails               VALIDATION REQUIRED BY CI
Radar scientific precipitation decode      PENDING
GFS evidence-variable decode               PENDING
Scientific Feature Engine                  NOT YET
Historical reconstruction                  NOT YET
Risk Engine                                DISABLED
```

## Next phase

Phase 1C will implement scientific feature reproduction in two streams:

1. GFS scientific decoder, driven by this registry.
2. Radar scientific precipitation/object decoder, driven by Hirockawa-family morphology definitions.

The first implementation target should be the lowest-ambiguity features that can be reproduced exactly from current GFS levels, especially 500/700 hPa RH, 600 hPa U/V, 850 hPa U/V, and the 1000–900 hPa water-vapor-flux stack. Higher-risk transformations such as 500 m interpolation, omega-to-geometric vertical velocity, LFC/EL reconstruction, and SREH storm-motion methods remain separately gated.
