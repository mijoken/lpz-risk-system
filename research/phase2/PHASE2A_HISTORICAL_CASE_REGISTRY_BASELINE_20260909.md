# Phase 2A Historical Case Registry Baseline — 2026-09-09

## Status

**PASS — official positive-source ingestion and normalized realized-positive anchor registry proven.**

Phase 2A starts Historical Feature Reconstruction without opening the LPZ risk engine.

## Official JMA source audit

The official JMA LPZ CSV source family was acquired successfully for 2023, 2024, 2025 and the current 2026 file.

Observed real CSV schema is identical across the four files:

1. 年
2. 月
3. 日
4. 時
5. 分
6. 府県予報区
7. 一次細分区域
8. 一次細分区域コード
9. 実況基準到達
10. 10分先基準到達
11. 20分先基準到達
12. 30分先基準到達

The physical first line is a metadata preamble such as `最終更新時刻:YYYYMMDDhhmmss`; it is not the tabular header. The initial parser assumption was corrected and a regression test now protects this behavior.

Observed source-row counts:

- 2023: **610**
- 2024: **183**
- 2025: **341**
- 2026 current file at this baseline: **218**
- total official detection rows: **1,352**

No duplicate source-row hashes were observed within the audited files.

## Entity semantics

The official CSV is treated as a **detection time/region table**, not as a pre-grouped independent-event table.

Two normalized entities are created:

### DETECTION_ROW

Every official row is retained with:

- stable ID;
- source provenance and row SHA256;
- JST/UTC analysis time;
- forecast area;
- primary subdivision and six-digit code;
- criterion-reached offsets among 0 / 10 / 20 / 30 minutes;
- raw official criterion markers.

### REALIZED_POSITIVE_ANCHOR

Only a `DETECTION_ROW` containing `実況基準到達 = 0` becomes a realized positive anchor.

Run 65 produced:

- all detection rows: **1,352**
- realized positive anchors: **851**
- forecast-only detection rows: **501**

Realized anchors by source year:

- 2023: **395**
- 2024: **106**
- 2025: **213**
- 2026 current: **137**

Each realized anchor receives the frozen reconstruction schedule:

- T-180
- T-120
- T-90
- T-60
- T-30
- T0

## Critical non-independence guardrail

**851 realized anchors are not interpreted as 851 independent LPZ episodes.**

The same physical rainband/system may be represented repeatedly at ten-minute analysis intervals and may be present in more than one primary subdivision. Therefore:

- `event_episode_id = null`;
- `episode_grouping_status = NOT_GROUPED`;
- no random row split is allowed;
- no model training treats anchors as independent samples before defensible episode grouping is defined and validated.

## Hard-negative policy

The initial hard-negative schema is frozen before negative cases are generated.

Primary candidate classes are:

- heavy rain without official realized LPZ;
- moving linear rainband without LPZ label;
- short-lived organized convection;
- intense convective cluster without persistence;
- high environmental favorability without LPZ;
- objective-rainfall near miss.

Trivial fair-weather random negatives are not the primary comparator.

A candidate in the same primary subdivision within ±180 minutes of a realized-positive anchor is excluded from initial HARD_NEGATIVE labeling. Cross-subdivision adjacency is deliberately left for a later explicit spatial-buffer audit rather than guessed now.

## Historical reconstruction capability

Historical features are classified as `EXACT`, `DERIVABLE`, `PROXY_REANALYSIS`, or `BLOCKED`.

Current important gates:

- official positive label: **EXACT** via JMA official CSV;
- 1-hour analyzed rainfall: **EXACT_SOURCE_PRODUCT** via JMA annual analyzed-rainfall data when acquired;
- 3-hour rainfall screening: **DERIVABLE** from time-aligned analyzed-rainfall fields;
- RH500/RH700, 600-hPa wind and 850-hPa inflow: **PROXY_REANALYSIS** using ERA5, always tagged as ERA5-derived rather than live-GFS-equivalent;
- high-resolution 30/50/80 mm/h morphology, parent tracking and embedded-core genesis: **BLOCKED_PENDING_HIGH_RES_RADAR**;
- preferred research source for high-resolution historical radar: **DIAS XRAIN CXMP**, but access is explicitly `REQUIRES_PERMISSION`;
- Hirockawa exact 3-hour HRA reproduction: **BLOCKED_EXACT_REPRODUCTION_NOT_YET_PROVEN**.

## XRAIN access guardrail

The XRAIN path is not treated as available merely because the dataset exists. The project records:

- DIAS account required;
- MLIT XRAIN dataset permission required;
- original-data redistribution is not allowed;
- permission status must remain `REQUIRES_PERMISSION` until actual access is proven.

## Current gates

```text
JMA official source transport              PASS
JMA real-header parsing                    PASS
Detection-row normalization                PASS
Realized-positive anchor extraction        PASS
Snapshot schedule                          PASS
Historical exactness policy                CI ENFORCED
Hard-negative selection policy             CI ENFORCED
Episode grouping                           NOT DONE
Hard-negative registry                     NOT BUILT
High-resolution historical radar           BLOCKED / PERMISSION PATH
Historical feature reconstruction          NOT STARTED
Final holdout                               NOT FROZEN
Risk engine allowed                        NO
```

## Next gate

The next engineering gate is **historical precipitation-data acquisition and hard-negative candidate generation**.

The project must first obtain a permitted historical precipitation source. JMA annual 1-km analyzed rainfall can support heavy-rain / near-miss screening after acquisition and format validation. High-resolution morphology-qualified negatives remain blocked until an approved high-resolution historical radar source, preferably DIAS XRAIN CXMP or another verified compatible source, is actually accessible.

No feature selection, threshold discovery, or risk-score construction is allowed before positive/negative reconstruction and temporal split design are complete.
