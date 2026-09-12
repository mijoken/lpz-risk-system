# LPZ Risk System

Explainable scientific monitoring and prediction system for linear precipitation zones in Japan.

> [!IMPORTANT]
> **Read `LPZ_SYSTEM_CHARTER.md` before changing architecture, scheduling, deployment, public UI, or scientific release policy.**
>
> Recovery keyword for a new chat/session: **`LPZ憲章復元`**  
> ASCII alias: **`LPZ-CHARTER-RESTORE`**
>
> When this keyword is used, reconstruct the project state from the charter, the machine-readable charter, latest `main` commits, Phase 2 freeze artifacts, workflows, and `web/` before modifying code.

> **Research / experimental system.** This repository is not an official weather warning service and must not replace information issued by the Japan Meteorological Agency (JMA) or local authorities.

## System identity

The final production system is **GitHub-hosted and externally published**:

```text
Weather / observation / forecast sources
        ↓
GitHub Actions + Python
  acquisition / decoding / validation
  scientific feature generation
  prediction / risk calculation after release gate
  audit / public JSON generation
        ↓
JSON / GeoJSON
        ↓
GitHub Pages
        ↓
HTML + CSS + JavaScript
        ↓
Public Japan-map dashboard
```

**Python computes data. JavaScript presents data.**

The public browser must not depend on a local Windows PC or Python runtime.

Authoritative architecture policy:

- `LPZ_SYSTEM_CHARTER.md`
- `config/lpz_system_charter.json`

## Current scientific state — 2026-09-12

The Development discovery and validation protocol are frozen.

Frozen Primary:

```text
q850_mean_kgkg @ t+0h
Positive > rainfall-matched Comparison
```

Current validation status:

```text
DEFERRED_PENDING_IMERG_FINAL_V08
```

IMERG Final V07 ends before the full frozen 2025 comparison universe can be reconstructed. The entire V07-supported target segment was completed, but none of the 23 Positive region-days has a fully observable frozen matching universe under V07.

Therefore:

```text
2025 Primary confirmatory test    NOT RUN
2025 ERA5 Primary outcome         SEALED
Risk engine                       LOCKED
Public validated risk score       NOT ALLOWED
Operational/system development    ALLOWED
```

Authoritative freeze:

- `research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json`

Gate:

```text
PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE
```

## Final V08 re-entry

When official IMERG Final V08 is available:

1. rebuild Development 2023–2024 consistently with Final V08,
2. rebuild 2025 Validation consistently with the same Final V08 family,
3. fit rainfall scaling/PCA on Development V08 only,
4. transfer that frozen transform to 2025,
5. apply the frozen same-region / ±60 calendar-day / ±3-day event-buffer / 1:3 no-replacement matching protocol,
6. freeze the matched 2025 population,
7. only then open 2025 ERA5 Primary outcomes,
8. run the frozen `q850_mean_kgkg @ t+0h` confirmatory test once,
9. do not retune after PASS or FAIL.

Do **not** patch only the missing 2025 tail with a different product/version.

## Production vs local development

### Final production target

- GitHub = canonical source of code/config/workflows/schemas/research/public small data products
- GitHub Actions = scheduled dynamic processing
- GitHub Pages = external public web surface
- JavaScript = JSON/GeoJSON rendering and Japan-map interaction

### Current local development environment

```text
D:\program\lpz-risk-system_dev
```

Local execution is for development, debugging, research processing, pre-commit verification, and temporary smoke testing only.

The current Windows Task Scheduler collector is **temporary** and must not be confused with the final production scheduler.

During the 2026-09-12 local migration/testing period, two GitHub schedules were temporarily removed:

- `b905fc1` — prospective collector cron removed
- `a184267` — prospective daily consolidation cron removed

Before production go-live, production scheduling must be restored/replaced on GitHub Actions and proven end-to-end.

## Public web target

The `web/` directory is the source of the public GitHub Pages experience.

Target separation:

```text
web/
├─ index.html
├─ css/
├─ js/
├─ assets/
│  └─ Japan / JMA-region GeoJSON
└─ data/
   ├─ latest.json
   ├─ source_health.json
   ├─ system_status.json
   └─ history/
```

The page should make the situation understandable at a glance:

- Japan map / region state,
- data-source freshness and health,
- system operating state,
- update time,
- validation state,
- whether the Risk Engine is released or locked.

Until scientific validation is released, the public site may show operational/research status but must not present an unvalidated LPZ probability or risk value as an operational prediction.

## Core scientific guardrails

The system must not silently:

- replace Kato's 500-m FLWV with a pressure-level proxy,
- use atmosphere to select rainfall-matched Comparison cases,
- change the frozen ±60-day / ±3-day / 1:3 matching policy to rescue validation,
- refit rainfall PCA/scaling on 2025 Validation,
- open 2025 ERA5 Primary outcomes before matching is frozen,
- change the frozen Primary because the validation path is inconvenient,
- use 2026 outcomes to tune the frozen 2025 Primary test,
- publish a validated operational risk score before the release gate.

Scientific evidence and formulas retain their original scope, dataset, units, resolution, and limitations.

Key evidence/requirements:

- `research/evidence/scientific_evidence_registry.json`
- `config/scientific_variable_requirements.json`
- `docs/architecture/SCIENTIFIC_EVIDENCE_ENGINE.md`

## Source policy

**Live mandatory**

- JMA High-Resolution Precipitation Nowcast
- JMA analyzed precipitation / RASRF
- JMA AMeDAS
- NOAA/NCEP GFS 0.25°

**Live supplementary**

- JMA WINDAS / wind profiler
- JMA Himawari imagery

**Benchmark only — never an independent score input**

- JMA official linear precipitation-zone detections / event records
- JMA LPZ short-range prediction products

**Historical core**

- ERA5
- JMA official LPZ event records
- historical radar where legally and technically available

## Data freshness and safe failure

Mandatory upstream data must expose observation/analysis time and age. If a mandatory source is stale or failed, the system must suspend risk output rather than silently reuse stale values.

## Repository policy

GitHub is the canonical source for code, configuration, research notes, schemas, workflows, and generated small JSON/GeoJSON products. Large raw weather datasets are not committed to Git.

## Recovery protocol

If the user says **`LPZ憲章復元`**, do not continue from conversational memory alone.

Mandatory recovery sequence:

1. read `LPZ_SYSTEM_CHARTER.md`,
2. read `config/lpz_system_charter.json`,
3. inspect latest `main` commits,
4. read Phase 2 H/K2 freeze artifacts,
5. inspect `.github/workflows/`,
6. inspect `web/` and current public data contract,
7. separate temporary local mechanisms from final GitHub production mechanisms,
8. summarize recovered state and next legitimate step before changing code.

## License

No project license has been selected yet. Third-party/public datasets remain subject to their own terms and attribution requirements.
