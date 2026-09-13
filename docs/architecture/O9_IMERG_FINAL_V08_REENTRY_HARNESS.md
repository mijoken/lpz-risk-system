# O9 — IMERG Final V08 Re-entry One-shot Harness

## Purpose

O9 implements the Phase 2L-K2 re-entry order without changing the frozen Phase H/K2 scientific protocol. Its first design rule is **fail closed**: while official Final V08 is unavailable, incomplete, schema-incompatible, not fully reconstructed, or the frozen 2025 rainfall-matched population is not cryptographically bound, O9 must remain in a WAIT/BLOCKED state and must not read 2025 ERA5 validation outcomes.

O9 does not authorize a public LPZ risk product. The Risk Engine and public validated risk output stay locked even if the frozen Primary eventually passes; scientific validation and legal/publication gates remain separate.

## Why O9 is separate from the old V07 scripts

The Phase H and K2 records preserve the historical source/code integrity of the V07-era discovery and freeze. O9 therefore adds new V08-specific/version-aware code instead of silently rewriting the old V07 implementation. The old files remain auditable evidence of what was frozen.

## Irreversible order

The only valid evidence prefix is:

1. `o9_a_v08_availability.json` — exact NASA Earthdata short name `GPM_3IMERGHH`, version `08`, official Final identity, at least one metadata result.
2. `o9_c_v08_required_coverage.json` — every exact half-hour slot required by all frozen Development 5,943 region-days and all frozen 2025 Validation 1,218 target region-days is available from the same Final V08 family.
3. `o9_d_development_v08_rebuild.json` — all 5,943 frozen Development region-days rebuilt under Final V08; no membership change and no environmental variable use.
4. `o9_d_validation_v08_rebuild.json` — all 1,218 frozen 2025 targets rebuilt under the same Final V08 family; all 23 official Positive region-days present; ERA5 still sealed.
5. `o9_e_development_v08_transform_freeze.json` — log1p means/std and PCA loadings fit on the 5,943 Development V08 rows only.
6. `o9_e_validation_v08_transform_application.json` — frozen Development V08 transform applied to 2025; zero 2025 standardization/PCA refit.
7. `o9_f_validation_matching_freeze.json` — same-region, ±60 circular calendar-day, ±3 actual Positive-day exclusion, 1:3 global no-replacement matching; 23 Positives + 69 comparisons = 92 immutable cases; environment not used. The Final-V08 P95-max 3-hour window start is preserved for every case.
8. `o9_g_2025_era5_opening_receipt.json` — **retrieval authorization only**. It may be created only after the complete real A–F chain and exact 92-case O9-F CSV are hash-verified. It authorizes ERA5 retrieval to begin; it does not say retrieval is complete and does not permit the Primary to run.
9. `o9_g_2025_era5_reconstruction_complete.json` — later completion evidence proving the authorized ERA5 reconstruction completed for the frozen 92 cases × four snapshots = 368 mappings without changing membership.
10. `o9_h_primary_confirmatory_result.json` — frozen `q850_mean_kgkg @ t+0h` Primary, equal-weight Positive-date cluster means, exact one-sided sign test, alpha 0.05, executed exactly once.

A later evidence artifact appearing while an earlier one is absent is a **safety-order violation**, not progress.

## Hash-linked evidence chain

Every stage after O9-A includes `requires_sha256` mapping predecessor evidence filenames to their SHA-256 digests. The controller recomputes these hashes. O9-G additionally verifies the exact authoritative Phase H/K2 freeze hashes and the SHA-256 of `o9_f_final_matched_population.csv`. This prevents a later ERA5/Primary result from being treated as valid after the rainfall population, transform, matching membership, or time anchors were silently replaced.

## O9-A — availability is not coverage

`GPM_3IMERGHH` version `08` metadata existence only opens O9-C. It is not enough to begin rainfall reconstruction and never opens ERA5.

The live availability probe is metadata-only:

```text
scripts/o9_v08_availability_probe.py
```

The existing V08 watch/source-health mechanisms remain the monitoring path; O9 does not add another recurring watcher.

## O9-B — version-aware payload compatibility

`src/lpz_risk/imerg_final.py` explicitly parses the IMERG filename product version and can be called with `expected_version="08"`. A V07 file is rejected. The decoder requires the expected `/Grid/precipitation`, `/Grid/lon`, and `/Grid/lat` schema and mm/hr units. If live V08 payload structure differs, O9 must stop at compatibility review rather than silently adapting scientific semantics.

## O9-C — exact required-slot coverage

For each frozen target UTC region-day, the existing frozen rolling-window semantics require 58 exact half-hour starts: previous-day 21:30 UTC through next-day 02:00 UTC. These support 53 six-slot rolling 3-hour windows from previous-day 21:30 through candidate-day 23:30.

O9-C requires zero missing slots for both populations. It does not interpolate, patch V07+V08, use IMERG Late/Early, or substitute another satellite.

## O9-G — guarded 2025 ERA5 opening

O9-G separates **authorization** from **retrieval completion**. This distinction is deliberate: possession of permission to retrieve ERA5 must never be mistaken for possession of the completed 2025 environmental dataset.

The network-free authorization gate is:

```text
scripts/o9_g_guarded_era5_opening.py
src/lpz_risk/o9_era5_opening.py
```

Before producing the authorization receipt it must verify all of the following:

- all real O9-A through O9-F evidence files exist with their exact expected gates;
- evidence marked synthetic cannot authorize real 2025 ERA5;
- the A→C→D→E→F `requires_sha256` chain is intact;
- O9-F is also bound to the authoritative Phase H and K2 freeze hashes;
- the exact `o9_f_final_matched_population.csv` SHA matches immutable O9-F evidence;
- the final population contains exactly 92 unique 2025 region-days: 23 `POSITIVE` and 69 `RAINFALL_MATCHED_COMPARISON_NOT_NEGATIVE_LABEL` cases;
- every one of the 23 match sets contains one rank-0 Positive and comparison ranks 1, 2, 3;
- every case preserves a valid timezone-aware `imerg_3h_p95_window_start_utc` and exact 3-hour P95 window;
- ERA5 request offsets remain exactly `-12h, -6h, -3h, 0h`;
- every requested timestamp is mapped to the latest whole ERA5 hour at or before the requested time; future ERA5 source time is forbidden;
- the frozen ERA5 provider, dataset, variables, pressure levels, 0.5° bbox padding and official JMA primary-subdivision geometry context remain intact.

The resulting request manifest has exactly **368 case/snapshot mappings (92 × 4)**. The authorization program itself is intentionally network-free: it does not import a retrieval client, contact CDS, read ERA5 values, run the Primary, or unlock risk.

Authorization receipt semantics:

```text
PASS_O9_G_2025_ERA5_RETRIEVAL_AUTHORIZED_AFTER_MATCHING_FREEZE
ERA5 retrieval may begin: YES
ERA5 reconstruction complete: NO
Primary may run: NO
Risk Engine: LOCKED
Public LPZ risk: LOCKED
```

Only a later reconstruction-complete receipt may move the controller to Primary eligibility:

```text
PASS_O9_G_2025_ERA5_RECONSTRUCTION_COMPLETE_92_CASES_368_SNAPSHOTS
```

ERA5 is never allowed to modify O9-F membership.

## Re-entry state transitions around O9-G

```text
O9-F real matching freeze complete
  -> READY_TO_CREATE_2025_ERA5_RETRIEVAL_AUTHORIZATION
     ERA5 may be opened = false
     Primary may run = false

O9-G authorization receipt complete
  -> READY_TO_RETRIEVE_2025_ERA5_WITH_GUARDED_RECEIPT
     ERA5 may be opened = true
     Primary may run = false

O9-G ERA5 reconstruction-complete receipt complete
  -> READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN
     Primary may run = true exactly once
```

## Current expected state while V08 is pending

Running the controller with no real O9 evidence is a successful safety outcome:

```text
WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN
ERA5 2025: SEALED
Primary confirmatory run count: 0
Risk Engine: LOCKED
```

This is not an operational error.

## Implemented units

- O9-A metadata-only Final V08 availability probe;
- O9-B version-aware payload compatibility guards;
- O9-C exact required-slot coverage gate;
- O9-D resumable V08 rainfall rebuild orchestration for Development and Validation;
- O9-E Development-only transform freeze and transfer to 2025;
- O9-F frozen validation matching and immutable 92-case population freeze;
- O9-G fail-closed, network-free ERA5 retrieval authorization gate;
- O9-G re-entry state split between authorization and reconstruction completion.

The later authenticated ERA5 retrieval/reconstruction implementation and the O9-H one-shot confirmatory executor remain separate stages. No later unit may weaken the Phase H/K2 rules.
