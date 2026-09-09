# Phase 1C Parent-Envelope / Embedded-Core Hierarchy Baseline — 2026-09-09

## Status

**PASS — nested 30/50/80 mm/h precipitation hierarchy proven on live JMA HRPN frames.**

Feature: `parent_envelope_embedded_core_hierarchy_public_png`

This is a descriptive hierarchy. It is **not** an LPZ classifier and does not yet claim back-building.

## Live proof

GitHub Actions run: **34334423235**

Four-frame sequence:
- 2026-09-09T08:50:00Z
- 2026-09-09T08:55:00Z
- 2026-09-09T09:00:00Z
- 2026-09-09T09:05:00Z

Fixed z8 4x4 mosaic inherited from the conservative tracking proof.

### Nested-threshold integrity

For every frame:
- every >=50 mm/h child core was assigned to a >=30 mm/h parent envelope;
- every >=80 mm/h child core was assigned to a >=30 mm/h parent envelope;
- every assigned child had **100% pixel containment** in its parent;
- unassigned child count was **0**.

Frame counts:

| Valid time | >=30 parents | >=50 cores | >=80 cores |
|---|---:|---:|---:|
| 08:50 | 42 | 13 | 2 |
| 08:55 | 43 | 10 | 4 |
| 09:00 | 46 | 14 | 6 |
| 09:05 | 41 | 14 | 7 |

## Embedded core genesis observation

A child-core lineage is logged as an `embedded_core_genesis_within_existing_parent` event when:
1. the child lineage is first observed in the tracking window; and
2. the assigned >=30 mm/h parent lineage was already present in the previous frame.

This is a structural observation only. It is **not** labeled back-building until upstream geometry, persistence, and historical validation are added.

Observed events:
- >=50 mm/h new cores inside existing parents: **15**
- >=80 mm/h new cores inside existing parents: **11**
- total: **26**
- parent lineages with at least one such event: **9**

Core-genesis counts by parent lineage:

| Parent lineage | >=50 births | >=80 births | Total |
|---|---:|---:|---:|
| T30-L0016 | 3 | 5 | **8** |
| T30-L0008 | 3 | 2 | **5** |
| T30-L0042 | 2 | 2 | **4** |
| T30-L0031 | 3 | 0 | 3 |
| T30-L0049 | 0 | 2 | 2 |
| T30-L0055 | 1 | 0 | 1 |
| T30-L0021 | 1 | 0 | 1 |
| T30-L0064 | 1 | 0 | 1 |
| T30-L0067 | 1 | 0 | 1 |

The repeated genesis in T30-L0016 is particularly useful as a test case for the next temporal descriptor stage, but it is not evidence by itself that the parent is an LPZ.

## Scientific interpretation

The previous overlap-only baseline showed that >=50 and >=80 mm/h cores are too volatile to serve as the sole system identity. The hierarchy proof resolves that problem cleanly:

```text
persistent broader precipitation envelope (>=30)
        |
        +--> >=50 core A: decay
        +--> >=50 core B: genesis
        +--> >=80 core C: genesis
        +--> >=80 core D: decay
```

This preserves the lifecycle of the broader system while treating intense convective cores as embedded phenomena.

That architecture is suitable for later tests of:
- parent-system stationarity;
- repeated embedded-core production;
- upstream versus downstream core genesis;
- parent motion versus environmental wind;
- back-building-like behavior.

## Guardrails

- child-core birth is not called back-building
- repeated child-core birth is not an LPZ gate
- no minimum number of genesis events is defined
- no overlap, speed, duration, or aspect-ratio threshold is promoted
- exact Hirockawa 3-h HRA remains blocked
- risk engine remains disabled

## Scientific gates after this baseline

```text
nested 30/50/80 hierarchy                   PASS
child-to-parent containment                 PASS
embedded-core genesis logging               PASS
repeated-core genesis by parent             PASS
parent temporal descriptor                  NEXT
upstream/downstream genesis geometry        PENDING
back-building descriptor                    PENDING
historical validation                       NOT STARTED
risk engine allowed                         NO
```
