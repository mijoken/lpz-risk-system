# LPZ Risk System — System Charter / 開発憲章

**Authority:** Highest-level project architecture and recovery policy for this repository.  
**Recovery keyword:** `LPZ憲章復元`  
**ASCII alias:** `LPZ-CHARTER-RESTORE`

> This charter exists specifically so that a new chat/session does not accidentally change the project's fundamental architecture. If a future assistant loses context, the recovery keyword requires it to reconstruct the project state from this repository before proposing or making changes.

---

## 1. Constitutional rule

The LPZ Risk System is ultimately a **GitHub-hosted, externally published, fully automated system**.

The production architecture is:

```text
Weather / observation / forecast sources
        ↓
GitHub Actions + Python
  acquisition
  decoding
  validation
  feature generation
  prediction / risk calculation (only after scientific release gate)
  audit / status generation
        ↓
Small public JSON / GeoJSON products committed or deployed from GitHub
        ↓
GitHub Pages
        ↓
HTML + CSS + JavaScript
        ↓
Public Japan map / charts / status dashboard
```

**Python computes data. JavaScript presents data.**

The browser must not depend on Python, a local PC, or a private runtime. GitHub Pages consumes JSON/GeoJSON produced by the GitHub-side pipeline.

---

## 2. Production vs local environment

### Production — canonical target

Production means:

- GitHub is the canonical source of code, configuration, workflows, schemas, research records, and small generated public data products.
- GitHub Actions performs scheduled dynamic processing and automation.
- GitHub Pages is the public web surface.
- JavaScript fetches repository/deployed JSON and GeoJSON and renders the Japan map and other views.
- The prediction page is intended to be externally accessible.
- The public UI must remain usable without the developer's Windows PC.

### Local Windows environment — development only

Current local development root:

```text
D:\program\lpz-risk-system_dev
```

The local environment is for:

- development,
- debugging,
- high-volume research processing,
- pre-commit verification,
- temporary operational smoke tests,
- reducing unnecessary GitHub Actions usage during development.

**Local execution is not the final production architecture.**

The Windows Task Scheduler collector (`LPZ-Prospective-Collector-15min`) is a **temporary development/verification harness**. It must not be mistaken for the final production scheduler.

### Historical transition — 2026-09-12

As of 2026-09-12, GitHub scheduled prospective collection/consolidation was temporarily disabled during local migration/testing. Relevant transition commits include:

- `b905fc1` — removed the scheduled GitHub prospective collector cron during local migration.
- `a184267` — removed the scheduled GitHub prospective daily consolidation cron during local migration.

These commits were temporary migration steps, **not** a declaration that production should remain local.

### Current operational transition — 2026-09-13

GitHub-side prospective operation has now been restored and redesigned under **Phase 2L-O8.1** so that GitHub cron is only a wake-up signal, not the scientific clock. The canonical scientific clock is the UTC 15-minute `collection_slot_utc` grid.

The operational chain is now:

```text
O8.1-A  JMA retention census
   PASS
     ↓
O8.1-B  exact historical-slot replay + GFS as-of guard
   PASS
     ↓
O8.1-C  self-healing batch collector
   PASS
   catch-up horizon = 120 minutes
     ↓
O8.1-D  canonical UTC daily consolidation
   PASS
   exactly 96 canonical 15-minute slots/day
     ↓
O8.1-E  consecutive-day completeness observer
   implemented and operational
     ↓
O8.1-F  final GitHub-only cutover audit
   canonical authority for Windows-task retirement
```

The legacy O8 rule that expected GitHub cron itself to execute roughly 96 times/day is **retired**. GitHub schedule timing is not treated as a scientific sampling clock. Missing slots within the audited horizon are recovered by the self-healing collector, with prospective as-of-time protection.

The authoritative current cutover report is:

```text
research/operations/o8_1_f_final_cutover_latest.json
```

As of the 2026-09-13 charter amendment, O8.1-F is correctly in:

```text
WAIT_KEEP_WINDOWS_TASK
```

with the sole remaining operational evidence blocker:

```text
TWO_CONSECUTIVE_CANONICAL_96_OF_96_DAYS
```

The temporary Windows task must therefore remain enabled until O8.1-F itself returns:

```text
PASS_READY_TO_DISABLE_WINDOWS_TASK
```

**Only O8.1-F may recommend retiring `LPZ-Prospective-Collector-15min`.** Even after O8.1-F passes, disabling the Windows task is a manual operational action; O8.1-F does not disable it automatically.

This operational cutover gate is completely separate from the scientific LPZ Risk Engine release gate.

---

## 3. Public web architecture

The public page is a first-class product, not an afterthought.

Target structure:

```text
web/
├─ index.html
├─ css/
│  └─ app.css
├─ js/
│  ├─ app.js
│  ├─ map.js
│  └─ charts.js
├─ assets/
│  └─ japan_regions.geojson
└─ data/
   ├─ latest.json
   ├─ source_health.json
   ├─ system_status.json
   └─ history/
```

Exact filenames may evolve, but the separation of responsibilities is constitutional:

- **GitHub Actions / Python:** produce validated JSON/GeoJSON.
- **GitHub Pages / JavaScript:** fetch and display those products.
- **Map:** Japan-centered and visually interpretable at a glance.
- **Geographic unit:** prefer the project's JMA primary-subdivision model where scientifically appropriate, not merely prefecture-level coloring.

The web page should make the current situation understandable immediately, including:

- geographic state,
- source freshness/health,
- system operating state,
- last update time,
- validation status,
- whether risk output is scientifically released or still locked.

---

## 4. Scientific release boundary

A polished public UI does **not** authorize an unvalidated prediction.

Current frozen scientific state:

- Primary confirmatory hypothesis remains `q850_mean_kgkg @ t+0h`, Positive > matched Comparison.
- 2025 Primary confirmatory validation remains deferred pending a consistent IMERG Final V08 reconstruction.
- IMERG Final V07 officially ends at 2025-09-30 for the required Final-series reconstruction.
- The complete V07-supported 2025 segment was reconstructed.
- The frozen matching universe is not fully observable for any of the 23 2025 Positive region-days under V07.
- 2025 ERA5 Primary outcome remains sealed.
- Risk Engine remains locked.

Authoritative freeze artifact:

```text
research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json
```

Gate:

```text
PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE
```

Until the release gate is scientifically resolved, the public page may display operational/system/research status, but must not present an LPZ probability/risk value as a validated operational prediction.

---

## 5. V8 re-entry rule

When IMERG Final V08 becomes available, do not patch only the missing 2025 tail onto V07.

The strict re-entry path is:

1. Verify official Final V08 availability and temporal coverage.
2. Rebuild the frozen Development 2023–2024 IMERG population consistently under Final V08.
3. Rebuild 2025 Validation targets consistently under the same Final V08 family.
4. Fit rainfall standardization/PCA on Development V08 only.
5. Transfer the frozen Development transform to 2025 without 2025 refitting.
6. Apply the frozen same-region, ±60 calendar-day, ±3-day event-buffer, 1:3 no-replacement matching protocol.
7. Freeze the resulting 2025 matched population.
8. Only then open 2025 ERA5 environmental outcomes.
9. Run the frozen `q850_mean_kgkg @ t+0h` confirmatory test once.
10. Do not retune after PASS or FAIL.

The Risk Engine may only be considered for release after this gate is resolved.

---

## 6. Non-negotiable scientific guardrails

Do not, without an explicit new user-approved protocol amendment:

- substitute IMERG Late/Early for missing Final data in the Primary validation,
- substitute GSMaP/CMORPH/another satellite only for the missing 2025 tail,
- shrink the frozen comparison universe merely to make validation executable,
- change the ±60-day seasonal window,
- change the ±3-day Positive event buffer,
- change the 1:3 no-replacement matching rule,
- refit PCA/scaling using 2025 Validation data,
- change the frozen Primary because the validation path is inconvenient,
- open 2025 ERA5 Primary outcomes before rainfall matching is properly frozen,
- use 2026 retrospective/prospective outcomes to tune the frozen 2025 Primary test,
- silently replace Kato 500-m FLWV with a pressure-level proxy,
- convert weak proxy relations into deterministic LPZ labels,
- enable an operational public risk score before the scientific release gate.

---

## 7. Source-of-truth hierarchy

When documents disagree, use this order unless the user explicitly amends the charter:

1. **Current explicit user instruction** that intentionally amends project policy.
2. **This charter** (`LPZ_SYSTEM_CHARTER.md`).
3. Machine-readable charter (`config/lpz_system_charter.json`).
4. Frozen research protocol artifacts under `research/phase2/`.
5. Current GitHub `main`, workflows, configuration, schemas, and code.
6. README and phase notes.
7. Old chat recollections or assistant memory.

The README may lag the true research phase; the charter and frozen protocol artifacts take precedence.

For the **current operational cutover state**, always read the live O8.1-F report rather than relying on the amendment-time status written in this charter:

```text
research/operations/o8_1_f_final_cutover_latest.json
```

---

## 8. Recovery keyword protocol

### Trigger

If the user says:

```text
LPZ憲章復元
```

or:

```text
LPZ-CHARTER-RESTORE
```

then the assistant must **not immediately continue coding from memory**.

It must first perform this recovery sequence:

1. Open and read `LPZ_SYSTEM_CHARTER.md`.
2. Open and read `config/lpz_system_charter.json`.
3. Inspect the latest commits on `main` and identify changes since the last known state.
4. Read the authoritative Phase 2 freeze artifacts, especially:
   - `research/phase2/phase2l_h_validation_protocol_freeze_20260911.json`
   - `research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json`
5. Inspect current production-facing files:
   - `.github/workflows/`
   - `web/`
   - public JSON/GeoJSON schema/output paths when present.
6. Read `research/operations/o8_1_f_final_cutover_latest.json` to recover the current GitHub-only cutover state.
7. Distinguish **temporary local development mechanisms** from **final GitHub production mechanisms**.
8. Summarize the recovered current state, current scientific lock, production architecture, and next legitimate step **before modifying code**.

The recovery keyword is a command to reconstruct state from GitHub, not a request to trust conversational memory.

---

## 9. Mandatory pre-change check for future assistants

Before proposing an architecture change, scheduling change, deployment change, or dashboard design, answer internally:

- Is this for local development or final production?
- Does it preserve GitHub Actions as the final dynamic-processing platform?
- Does it preserve GitHub Pages as the final public presentation platform?
- Does the UI consume JSON/GeoJSON via JavaScript?
- Does this accidentally expose an unvalidated risk score?
- Does it violate K2/V8 deferred-validation rules?
- If Windows-task retirement is being discussed, has O8.1-F actually returned `PASS_READY_TO_DISABLE_WINDOWS_TASK`?

If any answer is unclear, read the charter/repository again before proceeding.

---

## 10. Change control

This charter should be changed only when the user explicitly changes a fundamental system policy.

Any charter amendment should:

- update both `LPZ_SYSTEM_CHARTER.md` and `config/lpz_system_charter.json`,
- state the reason,
- be committed to GitHub,
- preserve prior scientific freezes unless the user explicitly authorizes a protocol amendment.

Suggested commit prefix:

```text
charter: ...
```

---

## 11. One-sentence system identity

> **LPZ Risk System is a GitHub Actions-driven scientific prediction pipeline that publishes small validated JSON/GeoJSON products to an externally accessible GitHub Pages JavaScript dashboard centered on a Japan map; local Windows execution is development-only, and operational risk output remains locked until the frozen scientific validation gate is passed.**
