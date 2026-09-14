# O9-H — Frozen Primary One-shot Confirmatory Executor / Ledger

## Purpose

O9-H is the irreversible 2025 confirmatory boundary. It exists to ensure that the sole Primary frozen in Phase 2L-H is evaluated **exactly once**, only after the complete O9-G ERA5 reconstruction is proven complete for the immutable 92-case population.

O9-H does not tune, select, rank, replace, rescue, or publish a model. It answers one pre-specified scientific question and preserves the answer even if the answer is FAIL.

## Frozen Primary

The authoritative source is:

`research/phase2/phase2l_h_validation_protocol_freeze_20260911.json`

O9-H revalidates the committed Phase H and K2 freeze hashes and requires:

- metric: `q850_mean_kgkg`;
- pressure level: 850 hPa;
- contrast: `t+0h`;
- snapshot offset: 0 h;
- match-set difference: Positive minus mean of the 3 rainfall-matched comparisons;
- cluster unit: `POSITIVE_DATE_UTC`;
- within-cluster aggregation: mean of match-set differences;
- Primary effect: equal-weight mean of Positive-date cluster means;
- test: `EXACT_ONE_SIDED_SIGN_TEST_ON_POSITIVE_DATE_UTC_CLUSTER_MEANS`;
- alternative: cluster mean difference > 0;
- exact zeros ignored;
- alpha: 0.05;
- PASS only if the effect estimate is > 0 **and** the exact one-sided sign-test p-value is < 0.05.

No multiplicity correction is applied to this single frozen Primary. Equality at p=0.05 is not a PASS.

## One-shot safety architecture

The real GitHub workflow is manual-only:

`.github/workflows/o9-h-frozen-primary-one-shot.yml`

It requires the operator to type the exact confirmation string:

`RUN_FROZEN_2025_PRIMARY_ONCE`

The irreversible path is deliberately split:

```text
O9-G reconstruction complete
  ↓
verify complete A→G chain + H/K2 freeze + snapshot SHA bindings
  ↓
create immutable reservation
  ↓
PUSH reservation to main
  ↓
create immutable execution seal for exact GitHub run/attempt/job identity
  ↓
PUSH execution seal to main
  ↓
ONLY NOW interpret q850 outcome values
  ↓
compute frozen Primary once
  ↓
write immutable pair/cluster artifacts + result
  ↓
PUSH result to main
  ↓
strict terminal audit
```

The GitHub attempt identity is:

`GITHUB_RUN_ID:GITHUB_RUN_ATTEMPT:GITHUB_JOB`

A GitHub re-run changes `GITHUB_RUN_ATTEMPT`; it therefore cannot reuse the previous reservation/seal as another authorized Primary read.

There is intentionally no reset, overwrite, retry-after-seal, or force flag.

## Reservation

Canonical file:

`research/o9/reentry/o9_h_primary_attempt_reservation.json`

The reservation is created with exclusive file creation and records, before Primary values are interpreted:

- exactly one confirmatory run;
- the exact attempt identity;
- O9-G completion SHA;
- O9-G snapshot CSV and JSON SHAs;
- Phase H and K2 freeze SHAs;
- canonical frozen Primary-definition SHA;
- every O9 A–G evidence-file SHA present in the readiness chain;
- `outcome_values_read=false`;
- `primary_confirmatory_test_run=false`;
- `automatic_rerun_allowed=false`;
- Risk Engine and public risk locked.

If the reservation already exists, another reservation is refused.

## Execution seal

Canonical file:

`research/o9/reentry/o9_h_primary_execution_seal.json`

The seal is written only after the reservation has been persisted. Before sealing, the runner recomputes every reserved evidence hash and the snapshot hashes and verifies the exact attempt identity.

The seal records that this exact attempt may cross the irreversible read boundary. It still records `outcome_values_read=false` and `primary_confirmatory_test_run=false` at seal time.

If the workflow crashes after the seal, the scientifically safe state is **manual forensic review**. A GitHub re-run is not authorization for a second Primary read.

## Primary calculation

The O9-G table contains exactly 368 rows: 92 cases × offsets `-12,-6,-3,0`.

O9-H revalidates the whole table and requires:

- 92 unique cases;
- 23 match sets;
- each set has rank 0 Positive and ranks 1,2,3 rainfall-matched comparisons;
- exactly four frozen offsets for every case;
- 23 Positive cases and 69 comparison cases;
- comparison role remains `RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL`;
- same primary subdivision within each match set;
- no future ERA5 source time;
- request-bbox spatial semantics unchanged;
- no risk score embedded in the snapshot table;
- finite, physically bounded q850 values.

Only t+0h is used for the Primary.

For each match set:

`difference = q850_positive - mean(q850_comparison_rank1, rank2, rank3)`

Each match-set difference is assigned to the Positive case's UTC date. Match-set differences sharing the same Positive UTC date are averaged. Those Positive-date cluster means receive equal weight.

For nonzero cluster means, if `k` of `n` are positive, the frozen one-sided p-value is:

`P[Binomial(n, 0.5) >= k]`

Exact zero cluster means are excluded from `n`.

## Robustness checks

O9-H computes only the robustness checks pre-specified before validation:

- cluster bootstrap, 20,000 resamples, 95% CI;
- leave-one-Positive-date-out support.

The implementation seed for deterministic reproducibility is `20260914`.

These checks are support-only. They cannot change a Primary FAIL into PASS. Secondary hypotheses and the historical 81-test exploratory panel are not run by this O9-H executor.

## Result

Canonical result:

`research/o9/reentry/o9_h_primary_confirmatory_result.json`

Supporting immutable artifacts:

- `o9_h_primary_match_set_differences.csv`
- `o9_h_primary_positive_date_clusters.csv`

The result SHA-binds the reservation, execution seal, O9-G completion, snapshot artifacts, Phase H/K2 freezes, and pair/cluster support artifacts. It records:

- `confirmatory_run_count=1`;
- Primary effect;
- sign counts including exact zeros;
- exact one-sided p-value;
- `primary_outcome=PASS|FAIL`;
- no retuning;
- no secondary/robustness rescue;
- no new feature, time offset, or threshold search;
- `confirmatory_run_may_execute=false`;
- `risk_engine_allowed=false`;
- `public_risk_release_allowed=false`.

A scientific FAIL is a valid terminal O9-H result and does not produce a workflow error merely because the hypothesis failed.

## Terminal audit

`scripts/o9_h_terminal_audit.py` independently verifies after the irreversible result exists:

- reservation/seal/result SHA links;
- exact attempt identity;
- H/K2 freeze hashes;
- frozen metric/contrast/estimand/test/alpha;
- pair and cluster artifact hashes and row counts;
- effect reconstructed from cluster artifact;
- exact one-sided sign-test result;
- PASS/FAIL consistency with the frozen rule;
- one-run count;
- all anti-retuning/anti-rescue guards;
- O9-G predecessor and snapshot bindings;
- Risk Engine and public-risk locks.

It cannot create, repair, reset, or rerun O9-H.

## Current state before Final V08 re-entry

The implementation and synthetic proof do **not** read the real 2025 ERA5 validation values and do **not** execute the real Primary.

Until the real A–G chain exists, the repository remains:

```text
WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN
2025 ERA5: SEALED
Primary confirmatory run count: 0
Risk Engine: LOCKED
Public LPZ risk: LOCKED
```

Even a future scientific PASS does not independently authorize public LPZ risk publication. The separate legal/publication gate remains required.
