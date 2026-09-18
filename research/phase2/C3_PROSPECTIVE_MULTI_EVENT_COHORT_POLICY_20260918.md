# C-3 Prospective JMA × IMERG Multi-event Cohort Policy

Date frozen: 2026-09-18

## Status

FROZEN BEFORE MULTI-EVENT EVALUATION.

This policy defines prospective evidence sampling only.

It does NOT define an LPZ classifier, rainfall threshold, warning threshold,
risk score, or production decision rule.

## Purpose

C-2 established a research-only structural comparison between:

- JMA HRPN public precipitation PNG interval classes; and
- NASA IMERG Early V07 native 0.1-degree half-hour mean rain rate.

C-3 tests whether the observed source-structure relationship persists across
multiple prospectively collected time windows.

## Selection-bias guardrail

A C-3 sampling slot MUST NOT be selected using:

- observed rainfall intensity;
- JMA precipitation class;
- radar morphology;
- radar temporal descriptors;
- parent precursor descriptors;
- IMERG precipitation;
- official LPZ occurrence;
- agreement or disagreement with C-2;
- model output;
- risk score;
- manual meteorological judgment.

Meteorological state is inspected only AFTER a sampling slot has entered the
cohort.

## Sampling clock

Reuse the existing deterministic UTC scientific-clock principle.

C-3 sampling slots are fixed at:

- 00:00 UTC
- 06:00 UTC
- 12:00 UTC
- 18:00 UTC

for each prospective UTC date.

The sampling schedule is independent of weather state.

## JMA raw evidence support

For each selected slot, preserve seven consecutive 5-minute JMA HRPN public
PNG frames spanning 30 minutes and ending at the selected slot.

The original PNG bytes are retained without alteration.

Each tile record preserves:

- basetime;
- validtime;
- zoom;
- x/y;
- source URL;
- HTTP status;
- Content-Type;
- byte count;
- SHA256;
- relative archive path.

## C-2 scientific policy remains frozen

JMA public PNG remains interval-valued.

Forbidden:

- class midpoint fabrication;
- reconstruction of exact continuous JMA mm/h;
- interpreting averages of class indices as rainfall;
- silently converting transparent pixels to zero rainfall.

IMERG Early remains native 0.1-degree half-hour mean rain rate.

Forbidden:

- spatial upsampling for the scientific comparison;
- treating IMERG as a JMA native-resolution field;
- direct continuous-rate equivalence claims.

## Cohort inclusion

A scheduled slot enters the attempted prospective cohort because of its clock
time alone.

Transport failure or source-retention failure does NOT remove the attempted
slot from the cohort.

Such cases remain explicit technical failures / missing evidence.

A failed slot MUST NOT be silently replaced by a meteorologically convenient
nearby slot.

## Technical proof exclusion

The C-3G capture:

2026-09-18 03:30–04:00 UTC

was collected before this cohort policy was frozen.

It is retained as a technical capture proof only and is NOT a C-3 prospective
multi-event cohort member.

## Evaluation boundary

Cohort membership is frozen before examining the meteorological result of each
scheduled slot.

Later descriptive stratification by precipitation state is allowed, but it
must not alter cohort membership.

No threshold tuning is permitted from prospective cohort outcomes.

## Authorization

risk_engine_allowed = false
production_integration_allowed = false

## Gate

prospective_sampling_rule             FROZEN
weather_conditioned_selection         FORBIDDEN
manual_event_cherry_picking           FORBIDDEN
failed_slot_replacement               FORBIDDEN
C3G_technical_proof_in_cohort         NO
risk_engine_allowed                   NO
production_integration_allowed        NO
