# F4 Research Closure Protocol — 2026-09-21

## Purpose

Prevent open-ended expansion of the F4 short-time radar motion research chain.
F4-5 through F4-9A established that:

- object-identity continuity is too brittle to be the primary verification axis;
- identity-free spatial verification is viable;
- the current constant-velocity centroid translation does not beat persistence overall;
- decoded four-frame z8 precipitation-class fields can be archived reproducibly for field-level motion research.

F4 now has a fixed endpoint. New F4-10/F4-11-style branches are prohibited unless this closure protocol is explicitly superseded before seeing new evaluation results.

## Frozen remaining stages

### Stage 1 — F4-9B: field-motion model specification freeze

One model family only:

- Lucas–Kanade field-level motion estimation;
- semi-Lagrangian advection for +15 min and +30 min;
- exact four-frame JMA HRPN z8 decoded fields;
- no LPZ probability, severity, or production Risk Engine output;
- no tuning against the existing F4-7/F4-8 evaluation sample;
- persistence remains the mandatory baseline.

This stage ends when the model inputs, transform, masking rules, motion-estimation parameters, extrapolation parameters, and verification metrics are frozen in code/tests before the prospective evaluation cohort is inspected.

### Stage 2 — F4-9C: one prospective head-to-head evaluation

A single prospective cohort is collected under the frozen F4-9B specification.

Cohort stop rule:

- stop when 100 exact future comparisons are available across both lead horizons, AND
- at least 3 distinct collection slots/events contribute comparisons,
- OR after 14 calendar days of eligible prospective collection, whichever occurs first.

No parameter retuning or model substitution is allowed during this cohort.

Primary comparison:

- paired best-IoU: optical-flow advection minus persistence, separately for +15 and +30 min.

Secondary comparisons:

- any-overlap rate;
- nearest observed >=30 mm/h component centroid distance;
- technical failure / missing-frame rate.

### Stage 3 — F4-9D: terminal Go / No-Go and F4 closure

GO to later integration research only if all of the following hold:

1. mean paired best-IoU delta is > 0 at both +15 and +30 min;
2. optical-flow any-overlap rate is not worse than persistence at both horizons;
3. optical-flow median nearest-centroid distance is not worse than persistence at both horizons;
4. no scientific lock, as-of, field-semantics, or Risk Engine invariant is violated.

Otherwise the decision is NO-GO.

Regardless of GO or NO-GO, F4 closes at F4-9D.

A NO-GO result means:

- persistence remains the short-time spatial baseline;
- constant-velocity F4-1 remains a research comparator only;
- field-level optical flow is not promoted;
- no additional F4 retuning loop is opened from the same cohort.

A GO result means:

- F4 closes successfully;
- any later production/integration work begins under a new explicitly scoped phase with its own exit criteria.

## Anti-expansion rule

During F4-9B/F4-9C/F4-9D:

- do not create F4-10, F4-11, or parallel rescue branches;
- do not change the frozen model after looking at prospective results;
- do not introduce a second optical-flow model for comparison;
- do not add post-hoc thresholds to rescue a failed endpoint;
- do not reinterpret failed primary metrics using secondary metrics.

If an implementation defect is found, fix only the defect and preserve the frozen scientific specification. If the specification itself is invalid, terminate F4 with NO-GO rather than silently redesigning it.

## General development rule adopted from this closure

For future research subprojects, define before execution:

1. the question;
2. the maximum remaining stages;
3. the data/cohort stop rule;
4. the primary endpoint;
5. the Go/No-Go rule;
6. what happens after No-Go.

This is intended to prevent technically interesting but open-ended research loops.
