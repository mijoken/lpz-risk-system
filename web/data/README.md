# `web/data/` — Public generated data surface

This directory is the public data interface consumed by GitHub Pages JavaScript.

Production ownership:

```text
GitHub Actions + Python -> web/data/*.json -> GitHub Pages JavaScript
```

Expected primary products:

- `system_status.json`
- `source_health.json`
- `latest.json`
- future `history/...`

These products must be generated and schema-validated by the GitHub-side production pipeline. They are not a place for manually authored prediction values.

Schemas live under:

```text
web/schema/
```

Current Risk Engine state is **LOCKED**. Until the scientific release gate is passed, region-level `risk` values in `latest.json` must remain `null`.

See:

- `LPZ_SYSTEM_CHARTER.md`
- `docs/architecture/PUBLIC_WEB_DATA_CONTRACT.md`
