# Phase 2E — Three-Layer Precipitation Strategy Baseline (2026-09-10)

## Decision

LPZ-RISK will use three precipitation data roles simultaneously rather than choosing only one source.

1. **PRIMARY_HISTORICAL** — JMA historical Analyzed Rainfall.
2. **PROSPECTIVE_NATIVE** — derived live JMA public-radar/GFS features archived prospectively from 2026-09-10 onward.
3. **BACKUP_SATELLITE** — JAXA GSMaP as preferred satellite backup/independent comparator, with NOAA CMORPH CDR as secondary backup.

The three source families are not interchangeable. Source identity and exactness are retained on every derived record.

## Primary historical rainfall

JMA historical Analyzed Rainfall remains the preferred historical precipitation product for the 2023–2025 development/validation period. It is not replaced silently by satellite rainfall.

Payload acquisition is still required. Decoder implementation will use the format documentation and decoder distributed with the actual media instead of reverse-engineering the binary format from assumptions.

## Prospective native archive

A new GitHub Actions collector runs at 15-minute cadence and derives:

- public-radar scientific class decode
- 30/50/80 mm/h morphology
- 600-hPa orientation comparison
- multi-frame object tracking
- parent/core hierarchy
- parent temporal descriptors
- parent-motion-relative genesis geometry
- 850-hPa inflow-relative genesis geometry
- parent precursor feature rows

Raw radar images and raw GRIB files are not archived by this layer. One compact derived-feature bundle is stored temporarily as a GitHub Actions artifact.

A separate daily consolidation workflow collects the prior UTC day's successful bundles and writes one compressed JSONL archive plus a manifest under `research/prospective/YYYY/MM/` in GitHub. Missing scheduled runs remain explicit gaps; they are never imputed silently.

### Live proof

Prospective collector Run 34403040464 completed successfully. All scientific derivation steps, feature-bundle construction, no-score guardrail, and artifact upload succeeded.

## Backup satellite policy

Priority:

1. JMA historical analyzed rainfall
2. GSMaP historical/standard rainfall
3. NOAA CMORPH CDR

Backup data may fill source gaps, but the selected source is recorded explicitly. When primary and backup coexist, disagreement is retained as a diagnostic rather than averaging sources.

Satellite products must not be treated as exact 1-km radar equivalents. They cannot directly inherit JMA-specific morphology thresholds or exact HRA semantics without separate validation.

## Frozen guardrails

- Never silently replace JMA primary with satellite rainfall.
- Never average JMA/GSMaP/CMORPH before frozen validation.
- Never use source disagreement itself to tune labels on the validation/test set.
- Hard-negative label remains `null` at candidate-generation stage.
- Risk score remains `null`; Risk Engine remains disabled.
- Prospective archive begins after the design freeze and is intended to support genuinely prospective evaluation.

## Current gates

```text
JMA historical source specification          PASS
JMA historical payload                       ACQUISITION REQUIRED
Prospective native collector                 PASS
15-minute schedule                           ENABLED
Daily GitHub consolidation                   IMPLEMENTED
GSMaP source role                            FROZEN / ACCESS SETUP PENDING
CMORPH source role                           FROZEN / PUBLIC ACCESS AVAILABLE
Primary-backup selector guardrail            IMPLEMENTED
Primary-backup disagreement diagnostic       IMPLEMENTED
Risk Engine                                  OFF
```
