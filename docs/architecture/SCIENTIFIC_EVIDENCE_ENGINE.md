# Phase 1B — Scientific Evidence Engine

## Purpose

LPZ-RISK does not treat published thresholds as unquestioned operational rules.
Peer-reviewed literature is converted into a machine-readable registry so that
paper-derived formulas, thresholds, object definitions, statistical findings,
limitations, and required input variables can be reproduced and compared on the
same historical cases.

## Core rule

**Evidence is not a gate.**

A paper may propose a useful threshold, but the threshold retains its original
region, season, data resolution, sample, and methodological limitations. It is
not promoted into the LPZ operational score until historical reconstruction,
validation, and a frozen holdout demonstrate incremental value.

## Initial curated evidence families

1. **Kato (2020) six favorable conditions**
   - 500 m water-vapor flux
   - distance to LFC
   - 500/700 hPa relative humidity
   - 0–3 km SREH
   - large-scale 700 hPa ascent
   - equilibrium level

2. **Hirockawa et al. (2020) / Hirockawa & Kato (2022)**
   - objective heavy-rainfall object extraction
   - aspect ratio / area
   - overlap / persistence
   - quality-control refinements

3. **Kato (2005)**
   - Kyushu-specific 850 hPa southwesterly persistence

4. **Shimamura et al. (2025)**
   - 6,760-object reanalysis climatology
   - rainband orientation relationship with 600 hPa wind

5. **Hayashi et al. (2025)**
   - object-based forecast verification
   - Interest Value and SCS framework

6. **Kumagai et al. (2026)**
   - Tohoku regional threshold sensitivity

7. **Tahara et al. (2026)**
   - 64-year northern-Japan analysis
   - vertically integrated 1000–900 hPa water-vapor flux and divergence
   - evidence against treating the Kato six conditions as a deterministic all-six gate

## Important implementation guardrails

### Exact 500 m diagnostics

Kato (2020) defines the low-level water-vapor-flux diagnostic at **500 m
height**. A convenient GFS pressure level such as 950 hPa is not automatically
equivalent to 500 m. The registry therefore keeps this feature blocked from
being labelled an exact reproduction until an appropriate height-coordinate
reconstruction is implemented and validated.

### Six conditions are multi-evidence, not binary truth

The 2026 northern-Japan study found that all six criteria were satisfied by
only part of the event population. LPZ-RISK will therefore retain each
condition as a separate diagnostic and also compute a condition-count /
coverage field, but will not require all six conditions for an LPZ event.

### Regional threshold policy

Uniform precipitation thresholds can distort the detected object itself.
Tohoku studies show that relaxing a rainfall threshold can both add events and
cause previously detected events to disappear because object area, aspect
ratio, overlap, or target-location criteria change. Regional thresholds must
therefore be validated as an object-detection regime rather than tuned as a
single scalar.

## Pipeline position

```text
Scientific literature
        |
        v
Scientific Evidence Registry
        |
        +--> formula / threshold / finding
        +--> limitations / scope
        +--> required variables
        |
        v
Evidence-aware acquisition requirements
        |
        v
Canonical weather data
        |
        v
Scientific Feature Engine
        |
        v
Historical reconstruction + frozen validation
        |
        v
Only then: candidate risk fusion
```

## Machine files

- `research/evidence/scientific_evidence_registry.json`
- `src/lpz_risk/evidence.py`
- `scripts/validate_scientific_evidence.py`
- `tests/test_scientific_evidence.py`

The registry is intentionally small at first. Subsequent literature batches
will add papers only after source-level review and explicit extraction of what
can and cannot be reproduced.
