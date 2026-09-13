# Phase 2L-O8.1 — Self-Healing Prospective Collection

## Purpose

O8.1 removes the incorrect assumption that a GitHub Actions `schedule` event is a precise scientific clock.

GitHub Actions remains the production execution environment, but cron is treated only as a **wake-up signal**. The scientific sampling clock is a deterministic UTC 15-minute slot grid. A delayed or skipped GitHub wake-up must not automatically become a missing scientific observation.

This phase is operational only. It does **not** unlock the LPZ Risk Engine and does not change the frozen 2025 validation protocol.

---

## 1. Core invariant: scheduler time != scientific sample time

Canonical prospective slots are:

```text
HH:00
HH:15
HH:30
HH:45
```

Every archived bundle gets a stable `collection_slot_utc` key.

`generated_at_utc` remains provenance for when GitHub actually executed the computation, but daily coverage and deduplication are keyed by `collection_slot_utc`, never by workflow-run creation time.

The radar tracking window for a slot is deterministic:

```text
slot-15m
slot-10m
slot-5m
slot
```

All four 5-minute frames must exist for the slot to be recoverable.

---

## 2. Why catch-up is possible, but bounded

JMA High-Resolution Precipitation Nowcast `targetTimes_N1.json` exposes multiple recent 5-minute analysis frames rather than only one latest frame. The observed interface currently exposes roughly three hours of recent frames.

Therefore a later GitHub run can reconstruct missed 15-minute slots while those source frames remain available.

However, source retention is a hard boundary. O8.1 must never invent a reconstructed slot after the required source frames are no longer available.

Before the catch-up horizon is treated as production policy, O8.1 shall measure and record the actually observed source-retention window. Until then, use a conservative safety horizon shorter than the visible source history.

---

## 3. Three archive roles

A bundle must explicitly identify how it was obtained.

### `PROSPECTIVE_NATIVE`

The slot was processed near real time, within the configured native-age threshold.

### `PROSPECTIVE_RECOVERED`

The slot was processed later because a GitHub wake-up was delayed or skipped, but the bundle was reconstructed only from inputs that satisfy the original as-of-time information policy.

Recovered data is never silently relabeled as native prospective data.

### `EXPLICIT_GAP`

The slot could not be reconstructed without violating source-retention or as-of-time rules.

An explicit gap is preferable to scientific contamination.

---

## 4. No future-information leakage during recovery

Catch-up is scientifically acceptable only if every time-varying input obeys an **as-of-time guard**.

For each slot define:

```text
prospective_as_of_utc = collection_slot_utc + settlement_lag
```

Radar analysis frames are anchored to the historical slot itself.

For forecast-model inputs such as GFS, the selected model cycle must have been available by the slot's prospective as-of time. A recovery run must never use a newer GFS cycle merely because that newer cycle is available when the delayed GitHub job finally executes.

Every recovered bundle records at minimum:

```text
collection_slot_utc
prospective_as_of_utc
generated_at_utc
archive_role
recovery_age_minutes
radar_frame_valid_times
model_cycle_time
model_forecast_valid_time
as_of_time_guard_pass
```

If the time-safe model cycle cannot be obtained, the slot is not promoted to a complete recovered bundle.

---

## 5. Deterministic slot-addressable scientific pipeline

The current live probes select a recent settled frame implicitly. O8.1 changes the radar/GFS pipeline so that a target slot can be supplied explicitly.

Required changes:

1. `radar_scientific_decode_probe.py`
   - accept a target/as-of time where needed;
   - do not silently jump to a later frame during recovery.

2. `radar_morphology_probe.py`
   - support an explicit target valid time.

3. `radar_tracking_probe.py`
   - accept `--target-valid-time`;
   - require the exact four-frame sequence ending at the requested slot;
   - never substitute a newer sequence.

4. GFS-dependent probes
   - select a model cycle under the as-of-time guard;
   - record the selected cycle and valid time.

5. `build_prospective_feature_bundle.py`
   - add slot identity and archive-role fields;
   - preserve `risk_score = null` and `risk_engine_allowed = false`;
   - preserve the rule that no-event states are descriptive and are not LPZ-negative labels.

---

## 6. Self-healing batch collector

A new orchestrator shall replace the assumption `one workflow run = one scientific sample`.

Conceptual flow:

```text
GitHub wake-up
    |
    v
read current JMA source window
    |
    v
compute settled 15-min slot grid
    |
    v
find slots not yet represented by recent successful collector artifacts / archive
    |
    +--> native current slot
    |
    +--> recoverable missed slots, oldest first
    |
    +--> unrecoverable old slots -> explicit gap ledger
    |
    v
process each slot deterministically
    |
    v
upload one batch artifact containing N slot bundles + batch manifest
```

The collector must be idempotent. Reprocessing an already represented slot is allowed, but daily consolidation must deduplicate by slot key.

A per-run cap prevents a delayed wake-up from causing an unbounded job. The cap must still cover the measured safe source-retention horizon.

---

## 7. Redundant GitHub wake-up paths

The prospective collector keeps its own scheduled trigger, but O8.1 adds a second internal wake-up path from the existing public production workflow.

Conceptually:

```text
Prospective cron -----------+
                            +--> same self-healing collector
Public O6 workflow complete +
```

This stays GitHub-only and avoids a single scheduled-workflow trigger becoming a single point of failure.

Duplicate wake-ups are harmless because slot processing is idempotent and daily consolidation is keyed by `collection_slot_utc`.

No long-running `sleep` loop is used. GitHub-hosted runners must not be kept alive merely to emulate a clock.

---

## 8. Batch artifact contract

One workflow run may contain multiple slot bundles.

Suggested artifact layout:

```text
prospective-batch-<run_id>/
  batch_manifest.json
  slots/
    20260913T060000Z.json
    20260913T061500Z.json
    20260913T063000Z.json
    ...
```

`batch_manifest.json` records:

```text
run_id
trigger_type
wake_time_utc
source_window_start_utc
source_window_end_utc
requested_slot_count
native_slot_count
recovered_slot_count
explicit_gap_count
technical_failure_count
slot_ids[]
risk_engine_allowed=false
```

---

## 9. Daily consolidation v2

The current daily archive logic filters collector runs by the workflow run's creation date. That becomes invalid once a run can recover earlier slots.

O8.1 daily consolidation instead:

1. downloads collector batch artifacts from a broad enough run window;
2. scans every slot bundle recursively;
3. selects records by `collection_slot_utc` date;
4. deduplicates by exact slot key;
5. prefers a complete bundle over an incomplete one;
6. if multiple complete bundles exist, preserves the **earliest complete prospective capture** as canonical and records duplicate/divergence diagnostics;
7. emits explicit gap rows where a canonical slot is absent.

Expected slots remain exactly 96 per UTC day.

The daily manifest adds:

```text
native_slot_count
recovered_slot_count
explicit_gap_count
technical_incomplete_count
canonical_slot_count
coverage_fraction
native_fraction
recovered_fraction
max_recovery_age_minutes
duplicate_slot_count
divergent_duplicate_count
```

---

## 10. O8 closure gate v2

O8 must stop judging production health by `scheduled_runs_in_lookback >= 80`.

GitHub cron frequency is a liveness signal, not the scientific-completeness metric.

The Windows Task Scheduler may be retired only when all of the following are demonstrated:

### Configuration

- prospective cron configured;
- public O6 cron configured;
- redundant internal wake-up path configured;
- daily archive configured;
- Risk Engine remains locked.

### Scientific collection integrity

For **two consecutive completed UTC days**:

```text
canonical_slot_count = 96
explicit_gap_count = 0
technical_incomplete_count = 0
parse_error_count = 0
risk_engine_allowed = false
```

Recovered slots are allowed, but are counted separately from native slots.

### Recovery integrity

- every recovered bundle passes the as-of-time guard;
- no recovered slot uses a future model cycle;
- no slot older than verified source retention is fabricated;
- duplicate divergence is surfaced explicitly.

### Runtime liveness

At least one GitHub wake-up must occur often enough that the verified source-retention window can still recover all missed slots. This is assessed against measured retention, not an arbitrary requirement for 80 or 96 workflow runs per day.

Until all gates pass, recommendation remains:

```text
KEEP Windows Task Scheduler enabled
```

---

## 11. Public Pages policy

The public observation dashboard does not need 96 successful workflow invocations per day. Its operational criterion is freshness of the latest valid public product.

Public Pages remains a separate concern from prospective scientific slot completeness.

The O6 public page may continue to display the latest settled precipitation frame even if some prospective archive slot required later recovery.

---

## 12. Implementation order

### O8.1-A — Retention census

Measure real replay availability for JMA radar frames and establish a conservative production catch-up horizon.

### O8.1-B — Slot-addressable pipeline

Add deterministic target-time support and GFS as-of guards.

### O8.1-C — Self-healing batch collector

Generate native + recovered slot bundles in one run and add redundant GitHub wake-up paths.

### O8.1-D — Daily consolidation v2

Consolidate by slot date, not run date; deduplicate and expose recovery diagnostics.

### O8.1-E — Closure audit v2

Replace workflow-count gating with 96-slot/day scientific completeness and recovery-integrity gates.

### O8.1-F — Two-day proof

Keep the Windows collector running in parallel until two consecutive UTC days pass O8.1 closure criteria. Only then disable `LPZ-Prospective-Collector-15min`.

---

## 13. Non-negotiable scientific guards

O8.1 must not:

- change the frozen 2025 Primary;
- open 2025 ERA5 outcomes;
- change rainfall-matching rules;
- convert no-event states into negative LPZ labels;
- silently mix native and recovered prospective data;
- use a future model cycle in a recovered slot;
- fabricate source data beyond measured retention;
- unlock or publish LPZ risk output.

The Risk Engine remains locked until the independent scientific release gate is satisfied.
