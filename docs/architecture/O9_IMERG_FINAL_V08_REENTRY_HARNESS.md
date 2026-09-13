# O9 — IMERG Final V08 Re-entry One-shot Harness

## Purpose

O9 implements the Phase 2L-K2 re-entry order without changing the frozen Phase H/K2 scientific protocol.  Its first design rule is **fail closed**: while official Final V08 is unavailable, incomplete, schema-incompatible, or not fully reconstructed, O9 must remain in a WAIT state and must not read the 2025 ERA5 validation outcomes.

O9 does not itself authorize a public LPZ risk product.  The Risk Engine and public validated risk output stay locked even if the frozen Primary eventually passes; scientific release and legal/publication gates remain separate.

## Why O9 is separate from the old V07 scripts

The Phase H and K2 records preserve the historical source/code integrity of the V07-era discovery and freeze.  O9 therefore adds new V08-specific/version-aware code instead of silently rewriting the old V07 implementation.  The old files remain auditable evidence of what was frozen.

## Irreversible order

The only valid evidence prefix is:

1. `o9_a_v08_availability.json` — exact NASA Earthdata short name `GPM_3IMERGHH`, version `08`, official Final identity, at least one metadata result.
2. `o9_c_v08_required_coverage.json` — every exact half-hour slot required by all frozen Development 5,943 region-days and all frozen 2025 Validation 1,218 target region-days is available from the same Final V08 family.
3. `o9_d_development_v08_rebuild.json` — all 5,943 frozen Development region-days rebuilt under Final V08; no membership change and no environmental variable use.
4. `o9_d_validation_v08_rebuild.json` — all 1,218 frozen 2025 targets rebuilt under the same Final V08 family; all 23 official Positive region-days present; ERA5 still sealed.
5. `o9_e_development_v08_transform_freeze.json` — log1p means/std and PCA loadings fit on the 5,943 Development V08 rows only.
6. `o9_e_validation_v08_transform_application.json` — frozen Development V08 transform applied to 2025; zero 2025 standardization/PCA refit.
7. `o9_f_validation_matching_freeze.json` — same-region, ±60 calendar-day, ±3 actual Positive-day exclusion, 1:3 no-replacement matching; 23 match sets / 69 comparisons; environment not used.
8. `o9_g_2025_era5_opening_receipt.json` — 2025 ERA5 may be opened only after step 7 is hash-frozen. ERA5 may not change membership.
9. `o9_h_primary_confirmatory_result.json` — frozen `q850_mean_kgkg @ t+0h` Primary, equal-weight Positive-date cluster means, exact one-sided sign test, alpha 0.05, executed exactly once.

A later evidence artifact appearing while an earlier one is absent is a **safety-order violation**, not progress.

## Hash-linked evidence chain

Every stage after O9-A includes `requires_sha256` mapping predecessor evidence filenames to their SHA-256 digests.  The controller recomputes these hashes.  This prevents a later ERA5/Primary result from being treated as valid after the rainfall population or transform was silently replaced.

## O9-A — availability is not coverage

`GPM_3IMERGHH` version `08` metadata existence only opens O9-C.  It is not enough to begin rainfall reconstruction and never opens ERA5.

The live availability probe is metadata-only:

```text
scripts/o9_v08_availability_probe.py
```

The existing V08 watch/source-health mechanisms remain the monitoring path; O9 does not add another recurring watcher.

## O9-B — version-aware payload compatibility

`src/lpz_risk/imerg_final.py` explicitly parses the IMERG filename product version and can be called with `expected_version="08"`.  A V07 file is rejected.  The decoder requires the expected `/Grid/precipitation`, `/Grid/lon`, and `/Grid/lat` schema and mm/hr units.  If live V08 payload structure differs, O9 must stop at compatibility review rather than silently adapting scientific semantics.

## O9-C — exact required-slot coverage

For each frozen target UTC region-day, the existing frozen rolling-window semantics require 58 exact half-hour starts: previous-day 21:30 UTC through next-day 02:00 UTC.  These support 53 six-slot rolling 3-hour windows from previous-day 21:30 through candidate-day 23:30.

O9-C requires zero missing slots for both populations.  It does not interpolate, patch V07+V08, use IMERG Late/Early, or substitute another satellite.

## Current expected state while V08 is pending

Running the controller with no O9 evidence is a successful safety outcome:

```text
WAIT_IMERG_FINAL_V08_NOT_AVAILABLE_OR_NOT_PROVEN
ERA5 2025: SEALED
Primary confirmatory run count: 0
Risk Engine: LOCKED
```

This is not an operational error.

## Later O9 implementation units

After A/B/C are proven, subsequent implementation adds:

- O9-D resumable V08 rainfall rebuild orchestration for Development and Validation;
- O9-E Development-only transform freeze and transfer to 2025;
- O9-F frozen validation matching and immutable matching-population freeze;
- O9-G ERA5 unlock receipt bound to the matching-freeze SHA;
- O9-H one-shot confirmatory executor/ledger that refuses a second run.

No later unit may weaken the Phase H/K2 rules.
