# F4-9D Terminal One-Shot Runbook — frozen preparation, 2026-09-22

Purpose: define the terminal execution gate before opening the real F4-9C prospective outcome.

ENTRY GATE
Do not run F4-9D merely because this runbook exists. Run only after the existing fixed F4-9C wrapper itself reports:
F4-9C SKIP: cohort is already ready for F4-9D.

Before that message appears, do not open cohort_status.json, verifications, comparison rows, per-case scores, or manually invoke the terminal finalizer.

FROZEN IDENTITIES
Runner worktree: D:\program\lpz-risk-system_f4_9c_runner
Expected runner commit: 6ed115f630ee55ecebd68c4c8001133f762c07a4
Expected finalizer Git blob: 843c2d332e13b914fa3503c972df2c064aff146a
Cohort root: D:\program\lpz-risk-system_f4_9c_cohort
Research Python: D:\program\lpz-risk-system_f4_9b_venv\Scripts\python.exe
Terminal output: D:\program\lpz-risk-system_f4_9c_cohort\f4_9d_terminal_decision.json
SHA sidecar: D:\program\lpz-risk-system_f4_9c_cohort\f4_9d_terminal_decision.sha256.txt

TERMINAL RULES
1. Verify runner HEAD and clean worktree.
2. Verify finalizer blob identity.
3. Refuse execution if terminal output or SHA sidecar already exists.
4. Run scripts/finalize_f4_9d.py exactly once against the real cohort.
5. Freeze SHA-256 sidecar immediately.
6. Report decision, both lead summaries, every frozen go_check, verified counts, distinct slots, and technical failure rate.
7. Never cherry-pick only favorable metrics.

OUTCOME HANDLING
GO: F4 closes successfully; any later integration/F5 work begins as a separately scoped phase.
NO_GO: F4 still closes; persistence remains the short-time baseline; do not reopen F4 on the same cohort.
In both cases: Risk Engine remains locked, no LPZ probability/severity/production forecast is created, and archived F4 geometry remains visible under the frozen dashboard protocol.

CURRENT STATUS
Static protocol/code preflight: PASS
Synthetic F4-9D tests: 5/5 PASS
Real F4-9C readiness: UNINSPECTED
F4-9D terminal artifact: NOT CREATED
F4 terminal decision: UNRUN
