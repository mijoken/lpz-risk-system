# LPZ Risk System — System Charter / 開発憲章

**Authority:** Highest-level architecture, scientific-lock, operational-transition, recovery, and change-control policy for this repository.  
**Effective revision:** 2026-09-27  
**Recovery keyword:** `LPZ憲章復元`  
**ASCII alias:** `LPZ-CHARTER-RESTORE`

> This charter exists so that a new chat/session, a context-loss event, or an assistant memory failure cannot silently change the project's premises.  
> **When memory and this repository disagree, reconstruct from GitHub first. 憲章 ＞ AIの記憶。**

---

## 0. Constitutional summary / 最上位原則

The LPZ Risk System is ultimately a **GitHub-hosted, externally published, GitHub-only production system**.

Production architecture:

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
Small JSON / GeoJSON products
        ↓
GitHub Pages
        ↓
HTML + CSS + JavaScript
        ↓
Public Japan map / charts / status dashboard
```

**Python computes data. JavaScript presents data.**

The public browser must not depend on a local Windows PC, local Python process, or a private runtime.

The local Windows machine is never to be reinterpreted as the permanent production architecture merely because it is temporarily doing operational work.

---

## 1. 2026-09-27 explicit operational premise / 今回追加する最重要前提

### 1.1 Temporary local collection through 2026-09-30

Because GitHub Actions usage is currently constrained during the development/transition period, prospective collection may be run temporarily on the local Windows notebook/Terminal through **2026-09-30**.

This is a contingency/development operation only.

It does **not** mean:

- production has moved to Windows,
- Windows Task Scheduler is the final scheduler,
- local uptime is a scientific requirement of the final system,
- a local-PC outage proves a GitHub production defect.

### 1.2 GitHub-only production from 2026-10-01

From **2026-10-01**, the production principle is:

```text
GitHub Actions + GitHub repository + GitHub Pages only
```

Continuous local Windows collection must not be silently retained as production after this date.

If GitHub-only readiness is not achieved by the cutover date, the correct response is:

1. report that GitHub-only cutover is not yet complete,
2. identify the blocking GitHub-side condition,
3. fix or explicitly defer it,
4. obtain explicit user approval for any exceptional temporary local fallback.

Do **not** redefine local execution as production merely to satisfy a deadline.

### 1.3 Interpretation of pre-cutover gaps

During the temporary local-collection period, a missing 15-minute slot may simply mean:

- the notebook was powered off,
- Terminal/Task Scheduler was not running,
- local network access was unavailable,
- the temporary local collector was intentionally not operating.

Such a gap is **not automatically a bug**.

Before opening a root-cause investigation for a pre-2026-10-01 gap, ask:

```text
Was local collection expected to be running at that slot?
```

If the answer is no, classify it as an expected temporary operational gap and do not over-investigate.

A gap becomes a technical defect candidate when, for example:

- the responsible collector was expected to be running but no record was produced,
- the slot was present upstream but omitted downstream,
- an as-of guard or deduplication rule malfunctioned,
- a parser/selection/consolidation bug is evidenced,
- or the user explicitly requests deeper investigation.

### 1.4 Backfill / recovery of temporary gaps

Recovering a missing slot is allowed when technically and scientifically valid.

Recovered data must:

- remain distinguishable from native prospective collection,
- preserve the original `collection_slot_utc`,
- preserve as-of-time rules,
- use the existing recovered-role semantics such as `PROSPECTIVE_RECOVERED` where applicable,
- never be silently rewritten as native,
- never erase evidence that the original slot was missed.

Backfill is useful; falsifying prospective provenance is prohibited.

---

## 2. Production vs local roles

### Production — canonical target

Production means:

- GitHub is the canonical source of code, configuration, workflows, schemas, research records, and small generated public products.
- GitHub Actions performs scheduled dynamic processing.
- GitHub Pages is the public web surface.
- JavaScript fetches repository/deployed JSON and GeoJSON and renders the dashboard.
- Public operation does not depend on the developer's Windows PC.

### Local Windows — development, research, temporary contingency

Canonical development root:

```text
D:\program\lpz-risk-system_dev
```

Local use is appropriate for:

- development,
- debugging,
- scientific research processing,
- pre-commit verification,
- smoke tests,
- temporary prospective collection while GitHub Actions usage is constrained,
- large downloads/computation that should not consume cloud limits,
- controlled backfill/recovery.

Local use is **not** authority to change production architecture.

Preferred development workflow:

```text
Normal ChatGPT
   ↓
complete copy-paste PowerShell / Python
   ↓
user executes locally
   ↓
user returns exact output
   ↓
diagnose / patch / test
   ↓
GitHub branch / PR / main
```

Avoid cloud-computer/Work execution unless explicitly requested.

---

## 3. Historical scheduling transition

### 2026-09-12 temporary schedule removals

Historical commits:

- `b905fc1` — prospective collector cron temporarily removed.
- `a184267` — prospective daily consolidation cron temporarily removed.

These were temporary migration/development measures, **not** a policy change making Windows the final production scheduler.

### O8.1 redesign

Phase 2L-O8.1 established that GitHub cron is a wake-up signal, not the scientific clock.

Canonical scientific clock:

```text
UTC 15-minute collection_slot_utc grid
```

Operational chain:

```text
O8.1-A  JMA retention census
   ↓
O8.1-B  exact historical-slot replay + GFS as-of guard
   ↓
O8.1-C  self-healing batch collector
   ↓
O8.1-D  canonical UTC daily consolidation
   ↓
O8.1-E  consecutive-day completeness observer
   ↓
O8.1-F  final GitHub-only cutover audit
```

The old rule that expected GitHub cron itself to run approximately 96 times/day is retired.

Current cutover authority/report:

```text
research/operations/o8_1_f_final_cutover_latest.json
```

Always read that file during recovery. Do not rely on an old chat summary of O8.1-F.

---

## 4. O8.1 gap semantics / 欠損の扱い

A canonical UTC day always has exactly 96 slot positions.

Slot state semantics must remain distinct:

- `COMPLETE`
- `TECHNICAL_INCOMPLETE`
- `EXPLICIT_GAP`

Do not convert one state into another for cosmetic completeness.

For acceptance of the **GitHub-only production runtime**, evidence should come from a period that actually represents GitHub-only operation, preferably on/after 2026-10-01 unless the user explicitly designates another test window.

Pre-cutover local-PC gaps must not be used by themselves to conclude that GitHub-only production is unstable.

Likewise, a real parser, selector, workflow, or consolidation defect must not be excused as "just a local gap."

**Operational gaps and software defects are different categories. Keep them separate.**

---

## 5. Scientific release boundary

A polished UI or successful operational collector does **not** authorize an unvalidated LPZ risk prediction.

Frozen Primary:

```text
q850_mean_kgkg @ t+0h
Positive > rainfall-matched Comparison
```

Current Primary validation status:

```text
DEFERRED_PENDING_IMERG_FINAL_V08
```

Current scientific lock:

- 2025 Primary confirmatory validation is deferred pending consistent IMERG Final V08 reconstruction.
- 2025 ERA5 Primary outcome remains sealed.
- Primary confirmatory test has not been run.
- Risk Engine remains locked.
- Public validated LPZ probability/risk output remains prohibited.

Authoritative artifact:

```text
research/phase2/phase2l_k2_v07_boundary_v08_deferred_validation_freeze_20260912.json
```

Gate:

```text
PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE
```

Operational completion and scientific release are independent gates.

---

## 6. Final V08 re-entry rule

When official IMERG Final V08 becomes available:

1. verify official Final V08 availability and coverage,
2. rebuild frozen Development 2023–2024 rainfall consistently under Final V08,
3. rebuild 2025 Validation rainfall consistently under the same Final V08 family,
4. fit scaling/PCA on Development V08 only,
5. transfer the frozen Development transform to 2025 without refitting,
6. apply the frozen same-region, ±60 calendar-day, ±3-day event-buffer, 1:3 no-replacement matching protocol,
7. freeze the resulting 2025 matched population,
8. only then open 2025 ERA5 environmental outcomes,
9. run the frozen `q850_mean_kgkg @ t+0h` confirmatory test once,
10. do not retune after PASS or FAIL.

Do not patch only the missing 2025 tail with a different IMERG family or alternate rainfall product.

---

## 7. Non-negotiable scientific guardrails

Without an explicit user-approved protocol amendment, do not:

- substitute IMERG Late/Early for missing Final data in Primary validation,
- substitute GSMaP/CMORPH/another source only for the missing tail,
- shrink the frozen comparison universe merely to make validation executable,
- change the ±60-day seasonal window,
- change the ±3-day event buffer,
- change the 1:3 no-replacement matching rule,
- refit PCA/scaling on 2025 Validation,
- change the frozen Primary to rescue a result,
- open 2025 ERA5 Primary outcomes before rainfall matching is frozen,
- use later prospective outcomes to tune the frozen 2025 Primary test,
- silently replace Kato 500-m FLWV with a pressure-level proxy,
- convert a weak proxy relation into a deterministic LPZ label,
- enable public operational risk before the scientific release gate.

---

## 8. F4 research closure / 短時間移動研究の扱い

F4 is closed.

Authoritative terminal artifact:

```text
research/phase2/F4_9D_TERMINAL_DECISION_20260927.json
```

Frozen terminal state:

```text
F4-9D decision = GO
F4 closed = true
verified comparisons = 542
verified distinct source slots = 3
permanent technical failures = 0
post-hoc retuning = prohibited
```

Meaning of GO:

- the frozen optical-flow comparison passed its pre-specified F4-9D criteria,
- a new separately scoped integration phase may be considered.

GO does **not** mean:

- production integration is enabled,
- the Risk Engine is unlocked,
- a validated LPZ forecast exists,
- LPZ probability or severity is generated.

Current invariant:

```text
production_integration_enabled = false
risk_engine_allowed = false
validated_forecast = false
```

Archived purple field-motion geometry is research-only. Stale archived geometry must not imply a current live forecast.

Do not reopen F4 with F4-10/F4-11-style rescue tuning unless the user explicitly creates a new protocol scope.

---

## 9. Public web architecture and semantics

The public page is a first-class product.

Responsibility split:

- **GitHub Actions / Python:** validated JSON/GeoJSON production.
- **GitHub Pages / JavaScript:** fetch and display.
- **Browser:** no Python dependency.
- **Map:** Japan-centered and immediately interpretable.

The UI should clearly expose:

- geographic state,
- data-source freshness,
- system operating state,
- last update time,
- scientific validation status,
- Risk Engine locked/released state,
- research-only vs operational semantics.

Research layers must never visually imply official JMA warning status or validated operational prediction unless such a release has actually occurred.

---

## 10. Development discipline / 完成させるための作業規律

### 10.1 GitHub is source of truth

GitHub `main` is canonical for:

- code,
- configuration,
- workflows,
- research protocols,
- evidence records,
- small public JSON/GeoJSON,
- durable project state.

Local files are working copies unless explicitly frozen into GitHub.

### 10.2 Before changing code

Before a new patch:

1. confirm branch and HEAD,
2. confirm working tree state,
3. read current canonical artifact relevant to the task,
4. identify whether the issue is scientific, operational, UI, or tooling,
5. avoid duplicating already completed work,
6. state expected effect and non-effect,
7. patch minimally,
8. add/adjust regression tests,
9. test locally,
10. inspect diff before commit/push.

### 10.3 Root cause before repair

Do not patch symptoms repeatedly.

For a failure, separate:

```text
observed symptom
→ failing stage
→ root cause
→ blast radius / severity
→ minimal correction
→ regression proof
```

### 10.4 Severity must be explicit

Classify whether a defect affects:

- one display,
- one historical case,
- one day,
- one parser family,
- operational collection,
- scientific validity,
- or whole-system production safety.

Do not perform a repository-wide audit for a local issue without evidence that the blast radius is broad.

### 10.5 Avoid redundant audits

Previous PASS evidence should not be re-audited from scratch unless:

- relevant code/data changed,
- contradictory evidence appeared,
- the artifact is missing,
- or the user explicitly requests it.

### 10.6 Never mix independent problems

Examples:

- a parser scope bug is not the same as a local-PC downtime gap,
- O8.1 operational cutover is not the same as V08 scientific validation,
- F4 GO is not Risk Engine release,
- a Git maintenance warning is not automatically scientific corruption.

Treat independent issues independently.

---

## 11. Safe-failure and provenance rules

Mandatory sources must expose observation/analysis time and freshness.

If mandatory data are stale or unavailable, the system should fail safely rather than silently reuse stale values.

Never:

- invent missing weather observations,
- rewrite recovered data as native,
- infer success from absence of an error message,
- convert missing evidence into PASS,
- delete inconvenient gaps from canonical history,
- expose experimental research as official operational warning.

---

## 12. Source-of-truth hierarchy

When information conflicts, use:

1. **Current explicit user instruction** that intentionally changes project policy.
2. **This charter** — `LPZ_SYSTEM_CHARTER.md`.
3. `config/lpz_system_charter.json`.
4. Frozen research/closure protocol artifacts.
5. Current GitHub `main`, workflows, configuration, schemas, and code.
6. Current operational status artifacts such as O8.1-F.
7. README and phase notes.
8. Old chats, assistant memory, summaries, and assumptions.

For dynamic state, live canonical artifacts can supersede a date-stamped status snapshot in this charter without changing constitutional policy.

**Never use assistant memory to override GitHub evidence.**

---

## 13. Recovery keyword protocol / 「AIアルツハイマー」対策

### Trigger

If the user says:

```text
LPZ憲章復元
```

or:

```text
LPZ-CHARTER-RESTORE
```

the assistant must not immediately continue coding from memory.

### Mandatory recovery sequence

```text
LPZ憲章復元
        ↓
1. LPZ_SYSTEM_CHARTER.md
        ↓
2. config/lpz_system_charter.json
        ↓
3. GitHub main latest commit / recent commits
        ↓
4. git branch / working-tree context if local output is supplied
        ↓
5. Phase 2H / K2 scientific freezes
        ↓
6. F4 closure artifact and current archived/public F4 semantics
        ↓
7. research/operations/o8_1_f_final_cutover_latest.json
        ↓
8. .github/workflows/
        ↓
9. web/ and public JSON/GeoJSON contracts
        ↓
10. distinguish temporary local operation from final GitHub production
        ↓
11. identify current unresolved issue(s) without reopening closed work
        ↓
12. summarize current state + next legitimate step
        ↓
13. only then modify code
```

### Recovery output must explicitly state

At minimum:

- current `main` SHA,
- current production architecture,
- whether current operation is temporary local or GitHub-only,
- current O8.1-F state,
- current scientific V08/Primary lock state,
- F4 terminal state,
- Risk Engine state,
- current known blocker/next task,
- what must **not** be changed.

---

## 14. Anti-amnesia checklist / 忘れてはいけないこと

Before proposing work, future assistants must verify these statements:

- Final production is GitHub-only.
- Temporary Windows operation does not redefine production.
- Through 2026-09-30, local prospective collection can create ordinary downtime gaps.
- Such pre-cutover gaps are not automatically bugs.
- Backfill must preserve recovered provenance.
- GitHub cron is a wake signal; `collection_slot_utc` is the scientific clock.
- O8.1 operational readiness and scientific Risk Engine release are separate.
- Primary remains `q850_mean_kgkg @ t+0h`.
- 2025 validation remains deferred pending Final V08.
- 2025 ERA5 Primary outcome remains sealed.
- Risk Engine remains locked.
- F4 is closed with GO, but production integration remains disabled.
- Do not retune F4 post hoc.
- Do not re-audit closed work without a reason.
- Do not treat a local operational gap as a systemic software defect without evidence.
- Do not treat a software defect as harmless downtime when logs show a real bug.
- GitHub evidence outranks assistant memory.

If any item is uncertain, restore from GitHub before proceeding.

---

## 15. Current status snapshot — 2026-09-27

This section is a **snapshot**, not permanent constitutional truth. Re-read live artifacts during recovery.

### Repository

Known `main` at this charter revision base:

```text
12ea90ab1a99a7a2be49dc872264e0354b3783e9
```

### F4

```text
F4-9D = GO
F4 closed = true
production integration = disabled
Risk Engine = locked
public archived field-motion decision label = GO
```

### O8.1-F

Latest canonical report at revision time:

```text
state = WAIT_KEEP_WINDOWS_TASK
cutover_ready = false
blockers:
  TWO_CONSECUTIVE_CANONICAL_96_OF_96_DAYS
  DAILY_CONSOLIDATION_RUNTIME_FRESHNESS
```

Do not freeze these blocker values into future reasoning; read the live report.

### Known 2026-09-27 O8.1-D defect under repair

A real consolidator defect was identified:

```text
recursive slots/*.json discovery
→ downstream F3/F4 research slot files were misread as O8.1-C prospective bundles
→ collection_slot_utc missing parse errors
→ STRUCTURAL_ERROR
```

This is a software bug and is separate from expected temporary local-PC downtime gaps.

For the observed 2026-09-26 day, 77/96 prospective slots were represented and 19 were explicit gaps in the failed consolidation output. Under the current temporary-local premise, those 19 gaps are **not to be deep-investigated by default**; they may be recovered if useful and scientifically valid.

---

## 16. Change control

This charter may be amended only when the user explicitly changes a fundamental policy or when a durable project invariant must be added.

Any amendment must:

- update both `LPZ_SYSTEM_CHARTER.md` and `config/lpz_system_charter.json`,
- update README when user-facing recovery guidance changes,
- state the reason,
- preserve existing scientific freezes unless explicitly amended,
- distinguish permanent policy from date-stamped status snapshots,
- be committed to GitHub.

Suggested commit prefix:

```text
charter:
```

---

## 17. One-sentence system identity

> **LPZ Risk System is a GitHub Actions-driven scientific weather research/forecast pipeline whose production state is GitHub-only and externally published through GitHub Pages using JSON/GeoJSON; local Windows execution is development/temporary contingency only, scientific Primary validation remains frozen pending IMERG Final V08, Risk Engine remains locked, and all recovery must reconstruct state from GitHub rather than assistant memory.**
