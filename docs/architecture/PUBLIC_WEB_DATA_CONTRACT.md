# Public Web Data Contract

This document defines the stable boundary between the production computation layer and the public GitHub Pages UI.

## Constitutional architecture

Production is:

```text
GitHub Actions + Python
        ↓
validated JSON / GeoJSON
        ↓
GitHub Pages
        ↓
HTML + CSS + JavaScript
        ↓
public Japan map / charts / status UI
```

Python computes. JavaScript presents.

The public browser must not depend on the developer's Windows PC or a Python runtime.

## Public products

The Pages UI consumes three primary JSON products:

### `web/data/system_status.json`

System-level operational and scientific release state.

Schema:

```text
web/schema/public_system_status.schema.json
```

This answers:

- Is the operational pipeline online?
- Is the scientific release gate still locked?
- Has the Primary confirmatory test run?
- Is the Risk Engine allowed?
- What public data files should the UI load?

### `web/data/source_health.json`

Freshness and health for public-facing source diagnostics.

Schema:

```text
web/schema/public_source_health.schema.json
```

This answers:

- Which mandatory/supplementary sources are healthy?
- What is the latest source time?
- Is a source fresh, stale, missing, degraded, or pending?

### `web/data/latest.json`

Region-level data rendered on the Japan map.

Schema:

```text
web/schema/public_latest.schema.json
```

Geographic unit:

```text
JMA_PRIMARY_SUBDIVISION
```

The UI joins `region_code` / `geometry_key` to the public GeoJSON produced in Phase 2L-O2.

## Scientific lock invariant

The public UI must never infer scientific release from visual appearance.

The authoritative field is:

```text
release.risk_engine_allowed
```

When it is `false`:

- every region `risk` must be `null`,
- `display_state` must not be `RISK_AVAILABLE`,
- JavaScript must render a clear validation/lock state,
- no probability, risk score, or risk category may be presented as a validated LPZ prediction.

The JSON Schema enforces this rule.

Current scientific state remains:

```text
Primary: q850_mean_kgkg @ t+0h
2025 confirmatory validation: DEFERRED_PENDING_IMERG_FINAL_V08
2025 ERA5 Primary outcome: SEALED
Risk Engine: LOCKED
```

## Versioning

`schema_version` follows semantic versioning.

- PATCH: documentation/generator fixes that do not alter the contract.
- MINOR: backward-compatible additive fields.
- MAJOR: breaking contract changes.

Pages JavaScript must:

- tolerate unknown additive fields,
- fail visibly rather than silently if an unsupported major version is received,
- never reinterpret `null` as zero,
- never use stale cached risk data when current release state is locked or suspended.

## Time conventions

All timestamps are UTC ISO-8601 date-time strings.

Examples:

```text
2026-09-12T02:30:00Z
```

No local-time timestamp is part of the public contract.

## Numeric conventions

Public JSON must not contain:

- NaN,
- Infinity,
- -Infinity.

Unavailable values are represented as `null`.

## Atomic publication

A production workflow should:

1. build all public products into a temporary directory,
2. validate every JSON product against its schema,
3. validate GeoJSON join keys,
4. replace/publish the public files only after all validations pass,
5. publish `system_status.json` in the same commit/deployment as the other public products.

A partial publication must be treated as a failed production cycle.

## Browser responsibility

JavaScript may:

- fetch JSON/GeoJSON,
- render the Japan map,
- color regions from already-authorized public fields,
- show source freshness,
- show system/validation state,
- render charts/history.

JavaScript must not:

- calculate the scientific LPZ model,
- invent missing risk values,
- infer release from observed radar features,
- override the scientific release lock.

## Production vs local

Local outputs are development artifacts only.

A feature is not considered production-complete until:

1. GitHub-side automation produces the required JSON/GeoJSON,
2. schemas validate,
3. GitHub Pages JavaScript consumes the products,
4. the externally accessible page renders correctly without the local PC.

See `LPZ_SYSTEM_CHARTER.md` for the highest-level project authority.
