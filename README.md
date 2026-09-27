# LPZ Risk System

Explainable scientific monitoring / forecasting research system for linear precipitation zones in Japan.

> [!IMPORTANT]
> **Before changing architecture, scheduling, deployment, public UI, scientific release policy, or operational cutover policy, read `LPZ_SYSTEM_CHARTER.md`.**
>
> Recovery keyword: **`LPZ憲章復元`**  
> ASCII alias: **`LPZ-CHARTER-RESTORE`**
>
> The recovery keyword means: **do not trust conversational memory; reconstruct the project from GitHub first.**

> **Research / experimental system.** This repository is not an official weather warning service and must not replace information issued by the Japan Meteorological Agency (JMA) or local authorities.

---

## 1. Constitutional source of truth

Authoritative project policy:

- `LPZ_SYSTEM_CHARTER.md` — highest-level development charter.
- `config/lpz_system_charter.json` — machine-readable mirror for code/audits.
- frozen artifacts under `research/phase2/` — scientific and research closure authority.
- current GitHub `main`, workflows, and operational status artifacts — dynamic implementation/state.

When these disagree with an old chat or assistant memory:

```text
GitHub charter / frozen artifacts / current main
        >
assistant memory / old conversation recollection
```

---

## 2. System identity

Final production architecture:

```text
Weather / observation / forecast sources
        ↓
GitHub Actions + Python
  acquisition
  decoding
  validation
  feature generation
  prediction / risk calculation only after release gate
  audit / status / public data generation
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

Final production is **GitHub-only**. The public browser must not depend on a Windows PC or local Python process.

---

## 3. Current transition rule — 2026-09-27

### Through 2026-09-30

Because GitHub Actions usage is constrained during development/transition, prospective collection may temporarily run on the local Windows notebook/Terminal.

This is only a temporary contingency.

```text
local collection != final production
```

If the notebook is powered off and slots are missed before cutover, those gaps are **not automatically software bugs**.

### From 2026-10-01

Production principle:

```text
GitHub Actions + GitHub repository + GitHub Pages only
```

If GitHub-only readiness is not complete by then, do not silently redefine Windows as production. Report the blocker and resolve or explicitly defer it.

### Backfill rule

Missing temporary slots may be recovered when scientifically valid, but recovered records must remain distinguishable from native prospective records, using existing semantics such as:

```text
PROSPECTIVE_RECOVERED
```

Do not rewrite recovered data as native and do not erase the fact that the original slot was missed.

---

## 4. Local development environment

Current development root:

```text
D:\program\lpz-risk-system_dev
```

Preferred workflow:

```text
Normal ChatGPT
   ↓
complete copy-paste PowerShell / Python
   ↓
user executes locally
   ↓
exact output returned
   ↓
diagnose / patch / test
   ↓
GitHub branch / PR / main
```

Use local execution for development, debugging, research, pre-commit tests, large downloads/computation, temporary collection, and controlled backfill.

Do not treat local execution as permanent production architecture.

---

## 5. O8.1 operational chain

The scientific clock is the UTC 15-minute `collection_slot_utc` grid. GitHub schedule timing is only a wake signal.

```text
O8.1-A  JMA retention census
   ↓
O8.1-B  exact historical-slot replay + GFS as-of guard
   ↓
O8.1-C  self-healing batch collector
   ↓
O8.1-D  canonical 96-slot UTC daily consolidation
   ↓
O8.1-E  consecutive-day completeness observer
   ↓
O8.1-F  final GitHub-only cutover audit
```

Current cutover authority:

```text
research/operations/o8_1_f_final_cutover_latest.json
```

Always read the current report rather than relying on a date-stamped README value.

The old rule that GitHub cron itself should run approximately 96 times/day is retired.

Canonical daily slot states remain distinct:

- `COMPLETE`
- `TECHNICAL_INCOMPLETE`
- `EXPLICIT_GAP`

Do not rewrite one state as another just to make a day appear complete.

---

## 6. Current scientific state

Frozen Primary:

```text
q850_mean_kgkg @ t+0h
Positive > rainfall-matched Comparison
```

Validation status:

```text
DEFERRED_PENDING_IMERG_FINAL_V08
```

Therefore:

```text
2025 Primary confirmatory test    NOT RUN
2025 ERA5 Primary outcome         SEALED
Risk Engine                       LOCKED
Public validated risk score       NOT ALLOWED
```

Authoritative freeze:

```text
research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json
```

Gate:

```text
PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE
```

Operational success does not unlock the scientific Risk Engine.

---

## 7. Final V08 re-entry

When official IMERG Final V08 becomes available:

1. verify official V08 availability and coverage,
2. rebuild Development 2023–2024 consistently with Final V08,
3. rebuild 2025 Validation with the same Final V08 family,
4. fit rainfall scaling/PCA on Development V08 only,
5. transfer the frozen transform to 2025 without refitting,
6. apply frozen same-region / ±60-day / ±3-day event-buffer / 1:3 no-replacement matching,
7. freeze the matched 2025 population,
8. only then open 2025 ERA5 Primary outcomes,
9. run the frozen `q850_mean_kgkg @ t+0h` confirmatory test once,
10. do not retune after PASS or FAIL.

Do not patch only the missing 2025 tail using another rainfall product/version.

---

## 8. F4 field-motion research is closed

Authoritative terminal artifact:

```text
research/phase2/F4_9D_TERMINAL_DECISION_20260927.json
```

Frozen state:

```text
F4-9D decision                 GO
F4 closed                      true
verified comparisons           542
verified distinct slots        3
permanent technical failures   0
production integration         disabled
Risk Engine                    locked
validated forecast             false
post-hoc retuning              prohibited
```

F4 GO means only that the frozen comparison met the pre-specified F4-9D rule and a **new separately scoped integration phase** may be considered.

It does **not** authorize production integration or a validated LPZ forecast.

Archived purple field-motion geometry is research-only and must not imply a current forecast.

---

## 9. Public web architecture

`web/` is the source of the GitHub Pages product.

Responsibilities:

- **GitHub Actions / Python:** acquire, validate, calculate, audit, and emit JSON/GeoJSON.
- **GitHub Pages / JavaScript:** fetch and display those products.
- **UI:** clearly separate current vs archived, research vs operational, system health vs scientific release, and project research vs official JMA information.

The page should expose at least:

- geographic state,
- source freshness/health,
- system state,
- last update,
- scientific validation state,
- Risk Engine locked/released state.

---

## 10. Development rules

Before changing code:

1. confirm branch, HEAD, and working tree,
2. read the relevant canonical artifact,
3. classify the issue as scientific / operational / UI / tooling,
4. avoid duplicating completed work,
5. state expected effect and non-effect,
6. patch minimally,
7. add regression proof,
8. test locally,
9. inspect diff,
10. then commit/PR.

Failure analysis should follow:

```text
symptom
→ failing stage
→ root cause
→ severity / blast radius
→ minimal correction
→ regression proof
```

Do not perform broad re-audits without evidence that the blast radius is broad.

Keep independent problems independent. Examples:

```text
parser bug                  != local-PC downtime gap
O8.1 operational cutover   != V08 scientific validation
F4 GO                      != Risk Engine release
Git maintenance warning    != scientific corruption
```

---

## 11. Scientific guardrails

Without an explicit protocol amendment, do not silently:

- substitute Late/Early/alternate rainfall data for missing Final data in Primary validation,
- shrink the frozen comparison universe to force validation,
- change ±60-day / ±3-day / 1:3 matching,
- refit PCA/scaling using 2025 Validation,
- open 2025 ERA5 Primary outcomes before matching is frozen,
- change the frozen Primary to rescue the outcome,
- tune the frozen test using later prospective outcomes,
- replace Kato 500-m FLWV with a pressure-level proxy,
- convert weak proxy evidence into deterministic LPZ labels,
- publish an operational validated risk score before the release gate.

---

## 12. Recovery protocol

If the user says:

```text
LPZ憲章復元
```

or:

```text
LPZ-CHARTER-RESTORE
```

do not continue from conversational memory.

Mandatory reconstruction:

```text
LPZ_SYSTEM_CHARTER.md
        ↓
config/lpz_system_charter.json
        ↓
latest GitHub main / recent commits
        ↓
Phase 2H / K2 scientific freezes
        ↓
F4 terminal closure artifact
        ↓
research/operations/o8_1_f_final_cutover_latest.json
        ↓
.github/workflows/
        ↓
web/ + public JSON/GeoJSON contract
        ↓
temporary local vs GitHub-only production distinction
        ↓
current unresolved issue(s)
        ↓
state summary + next legitimate step
        ↓
only then modify code
```

The recovery summary must explicitly state:

- current main SHA,
- current production architecture,
- current operational mode,
- O8.1-F state,
- V08/Primary scientific lock,
- F4 terminal state,
- Risk Engine state,
- current blocker/next task,
- what must not be changed.

---

## 13. Current snapshot — 2026-09-27

This section is only a snapshot; live artifacts take precedence.

At the charter v2 base:

```text
main = 12ea90ab1a99a7a2be49dc872264e0354b3783e9
```

F4:

```text
GO / CLOSED
production integration disabled
Risk Engine locked
public archived field-motion decision label GO
```

O8.1-F snapshot:

```text
WAIT_KEEP_WINDOWS_TASK
blockers:
  TWO_CONSECUTIVE_CANONICAL_96_OF_96_DAYS
  DAILY_CONSOLIDATION_RUNTIME_FRESHNESS
```

Known O8.1-D defect under repair:

```text
recursive slots/*.json discovery
→ downstream F3/F4 research slot files misread as prospective bundles
→ collection_slot_utc missing
→ STRUCTURAL_ERROR
```

This software defect is separate from expected temporary local-PC downtime gaps.

For the observed 2026-09-26 failed consolidation:

```text
represented complete slots = 77
explicit gaps              = 19
```

Under the current temporary-local premise, those 19 gaps are not to be deep-investigated by default. They may be backfilled if useful and scientifically valid.

---

## 14. License

No project license has been selected yet. Third-party/public datasets remain subject to their own terms and attribution requirements.
