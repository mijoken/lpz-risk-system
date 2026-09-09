# Phase 2B ERA5 Authenticated Access Gate — 2026-09-09

## Status

**PARTIAL PASS — GitHub secret and CDS authentication path proven; ERA5 pressure-level dataset licence not yet accepted.**

## Authenticated proof

GitHub Actions workflow:

- workflow: `LPZ ERA5 Authenticated Proof`
- run id: `34356909862`
- repository: `mijoken/lpz-risk-system`

The run proved:

- `CDSAPI_KEY` exists in GitHub Actions Secrets: **PASS**
- secret value was masked in logs: **PASS**
- Python `cdsapi` client initialized: **PASS**
- request reached Copernicus CDS: **PASS**
- positive registry rebuilt: **PASS**
- ERA5 spatial request manifest rebuilt: **PASS**
- ERA5 payload download: **BLOCKED**

CDS returned:

`403 Client Error: Forbidden`

with the explicit provider message:

`required licences not accepted`

The API key itself is therefore not the current blocker. The remaining external gate is acceptance of the required licence(s) for dataset `reanalysis-era5-pressure-levels` in the same Copernicus account associated with the API key.

## Security evidence

The workflow log showed the environment value only as GitHub's masked form `***`.

No credential value is written to repository files, JSON reports, artifacts, or research baselines.

## Machine gate

`config/historical_environment_era5.json` now records:

- `credential_present = true`
- `credential_verified_by_github_actions = true`
- `dataset_licence_status = NOT_ACCEPTED`
- `download_gate = BLOCKED_PENDING_DATASET_LICENCE_ACCEPTANCE`

`scripts/era5_authenticated_probe.py` now classifies this failure separately from invalid credentials and other HTTP failures.

## Next proof after licence acceptance

Re-run `LPZ ERA5 Authenticated Proof` with request index `0`.

Success requires all of the following:

1. non-empty ERA5 GRIB payload downloaded;
2. scientific decode step executes;
3. required pressure-level fields exist;
4. required fields contain finite values;
5. source remains explicitly tagged `ERA5 / PROXY_REANALYSIS`;
6. Risk Engine remains disabled.

## Current gate summary

```text
CDSAPI_KEY GitHub secret                     PASS
CDS client initialization                    PASS
CDS endpoint reached                         PASS
ERA5 dataset licence                         BLOCKED_NOT_ACCEPTED
ERA5 GRIB payload                            NOT ACQUIRED
ERA5 scientific decode                       NOT PROVEN
Historical environment reconstruction        NOT COMPLETE
Risk Engine                                  OFF
```
