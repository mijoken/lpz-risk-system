# F4-9D Static Preflight — 2026-09-22 (NO PROSPECTIVE PEEKING)

## Scope and strict boundary

This is a **source-code and protocol-only** readiness audit for the terminal
F4-9D decision. The real F4-9C `cohort_status.json`, `verifications/`,
per-case predictive scores, current verified counts, pending counts, and F4-9D
decision were **not inspected or computed**.

The Fukushima/Miyagi event-side audit is a separate descriptive case report:
`research/phase2/F4_20260921_TOHOKU_MORPHOLOGY_AUDIT.md`.
It provides real strong-rain structure evidence and F4↔IMERG Late
co-location, **not** F4-9C future prediction accuracy. It is neither added as
a new endpoint nor selected as a new validation subgroup.

## Frozen inputs examined

- `research/phase2/F4_RESEARCH_CLOSURE_PROTOCOL_20260921.md`
- `research/phase2/F4_9C_PROSPECTIVE_PROTOCOL_20260921.md`
- `research/phase2/F4_POST_9D_DASHBOARD_INTEGRATION_PROTOCOL_20260921.md`
- `scripts/finalize_f4_9d.py`
- `tests/test_f4_9d_terminal_decision.py`
- `scripts/run_f4_9c_cycle.py` on frozen runner ref
  `6ed115f630ee55ecebd68c4c8001133f762c07a4`
- `scripts/run_f4_9c_fixed_cycle.ps1` from current main, which pins its
  *separate runner worktree* to the frozen ref above.

GitHub blob comparison: frozen runner ref and current main contain the
**same file blob** for both `finalize_f4_9d.py`
(`843c2d332e13b914fa3503c972df2c064aff146a`) and its existing
terminal-decision test
(`78ba4d0eeca37f2b836769b20edd1a220163479b`).
The closure protocol blob also agrees
(`2f1071e5470766f42379a1737adba90491fbd4ba`).
These hashes are Git **blob IDs**, not SHA-256 file checksums.

## Terminal logic, inspected without running it on the real cohort

`finalize_f4_9d.py` accepts only:

- `READY_FOR_F4_9D_TARGET_MET`
- `READY_FOR_F4_9D_DEADLINE`

The frozen collection runner defines the first readiness state when at least
100 exact comparisons from at least 3 distinct verified source slots exist.
The deadline state is reached only after 14 days and after pending frozen cases
are resolved. Do not infer when either will happen from this preflight.

The terminal primary paired endpoint is mean
`optical_flow_best_iou - persistence_best_iou > 0` separately at both 15 and
30 minutes. Other mandatory checks are non-worse any-overlap rate and
non-worse median nearest target centroid distance at both leads, together
with scientific/as-of/risk invariant locks. Failure of any check yields NO-GO.
F4 closes for GO or NO-GO; no same-cohort retuning or F4-10/11 rescue.

The existing evaluator only reads verification rows once invoked by an
explicit terminal run. Its CLI uses `--output` with create-new write mode,
refusing an existing result file. **The terminal evaluator is NOT being
invoked by this static preflight.**

The frozen dashboard integration protocol displays ARCHIVED research geometry
whether GO or NO-GO; only the research-decision label may change. Risk,
severity, probability and validated-forecast switches remain false.

## No-peek next action: isolated synthetic terminal tests only

On the user's separate, **clean** local audit worktree, fetch and pin this
audit-only branch; then execute only:

```powershell
& "D:\program\lpz-risk-system_dev\.venv\Scripts\python.exe" -m pytest -q tests/test_f4_9d_terminal_decision.py
```

The existing five tests construct `tmp_path` synthetic cases and
verifications. They cover GO, NO-GO on failed primary, before-ready refusal,
scientific-invariant failure, and deadline with no exact verified rows.
They do **not** open the real `D:\program\lpz-risk-system_f4_9c_cohort`.
A local PASS confirms executable wiring, **not** prospective skill or cohort
readiness. Do not invoke `scripts/finalize_f4_9d.py --cohort-root <real>`
yet.

## Terminal run only after the previously frozen readiness gate

At the predeclared gate, ensure:
1. the fixed F4-9C runner itself has reached a terminal-ready state under
   its **original** cycle and no cases are pending after deadline;
2. the frozen F4-9D test and scientific locks pass;
3. run the frozen finalizer once, with a new immutable output file;
4. report both leads and all predeclared checks, even in NO-GO;
5. close F4, leave all production/risk outputs locked;
6. update only the dashboard research-decision label through the separately
   frozen publication contract.

Do not ask a separate assistant or workflow to read interim verification
metrics before gate maturity. Do not stop or change the user's existing
`LPZ-Prospective-Collector-15min` Scheduled Task as part of this audit.

## Explicitly excluded from this stage

- inspecting the real F4-9C status or exact-future verifications;
- rerunning or backfilling F4-9C;
- model, threshold or baseline edits;
- F5 threshold selection based on the September 21 event;
- running the terminal decision to 'see what happens' before readiness;
- merging the diverged audit-only branch into main without separate scope
  review.

**Status:** static protocol/code preflight PASS; local synthetic terminal tests
PENDING; actual F4-9C readiness UNINSPECTED, actual F4-9D decision UNRUN.
