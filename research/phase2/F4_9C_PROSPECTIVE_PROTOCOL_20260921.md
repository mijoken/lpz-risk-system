# F4-9C Prospective Head-to-Head Protocol — 2026-09-21

## Role

F4-9C is the single prospective evaluation cohort allowed by the F4 closure protocol. The F4-9B model is frozen before this cohort.

No model, parameter, threshold, area/speed gate, second optical-flow method, or post-hoc rescue rule may be introduced during F4-9C.

## Prospective source capture

A source case may be frozen only when:

- the exact four-frame source sequence is available;
- the latest source radar observation is exactly 15 minutes behind prospective_as_of_utc;
- the case artifact is finalized before the +15 minute target valid time;
- no future target observation has been read.

Source predictions are generated only by the frozen F4-9B implementation.

## Comparison unit

One comparison unit is one non-boundary source >=30 mm/h component with at least 2 pixels at one frozen lead (+15 or +30 minutes from prospective as-of).

The source components are defined at capture time and cannot be redefined after future observations are available.

Each source component is transported with the same frozen dense velocity field. Eulerian persistence leaves the same source component in place.

## Exact future truth

At verification time:

- the exact target valid time is required;
- the target uses the same z8 fixed mosaic geometry as the source case;
- future >=30 mm/h components use 8-connectivity;
- components smaller than 2 pixels are excluded;
- boundary-truncated target components are excluded;
- source/target object identity is never required.

## Primary endpoint

For each source component and lead:

1. compare the optical-flow component mask to every eligible future component;
2. take the maximum pixel-mask IoU (best_iou);
3. repeat for the persistence component mask;
4. define paired delta as optical_flow_best_iou - persistence_best_iou.

F4-9D will report the mean paired delta separately at +15 and +30 minutes.

## Secondary endpoints

For the same paired comparison rows:

- any-overlap rate;
- nearest target-component centroid distance in km.

If no eligible target component exists, both models receive best-IoU = 0, any-overlap = false, and the fixed-mosaic diagonal distance as a deterministic centroid-distance penalty.

If an optical-flow component becomes empty inside the fixed domain, the same domain-diagonal distance penalty is applied. This prevents missing predictions from being silently removed from the centroid-distance endpoint.

## Cohort stop rule

Collection begins with the first F4-9C cycle.

New source capture stops when either:

- verified + pending planned comparisons reach at least 100 AND at least 3 distinct source slots are represented; or
- 14 calendar days have elapsed.

Pending cases frozen before collection stopped are allowed to mature and are verified.

F4-9C is ready for F4-9D when either:

- at least 100 exact future comparisons from at least 3 verified source slots are available; or
- the 14-day deadline has passed and all already-frozen pending cases have resolved to exact verification or permanent technical failure.

Permanent technical failures contribute to the technical failure rate but not to exact-future comparison count.

## Anti-peeking rule

During F4-9C:

- no aggregate skill summary is emitted;
- cohort status contains only operational counts;
- per-case metrics are stored for later F4-9D aggregation but are not used to change collection or model behavior;
- parameter tuning is prohibited.

## Terminal next step

There is exactly one next research stage: F4-9D.

F4-9D applies the pre-frozen GO/NO-GO rule and closes F4 regardless of outcome.
