# F4 Dashboard Archive Separation Addendum — 2026-09-27

## Purpose

This addendum changes **display placement only** after user review of the public
dashboard. It does not alter F4-9B model mechanics, F4-9C collection,
verification rows, F4-9D criteria, thresholds, Risk Engine locks, or any
prospective scientific endpoint.

The previous dashboard integration protocol allowed stale F4-9C field-motion
geometry to remain on the main map if it was visibly marked ARCHIVED. In
practice, an archived 2026-09-21 purple field-motion layer remained drawn over
current precipitation several days later. Even with an ARCHIVED label in the
side panel, the map itself could be read as if the purple geometry described
current conditions.

## Superseding presentation rule

For the **main live precipitation map**:

- field-motion geometry is shown only while its public research product is
  fresh and status is AVAILABLE;
- if status is ARCHIVED, or browser-clock age exceeds max_age_minutes, the
  purple geometry is removed from the live map;
- the research side panel may retain the archived as-of, object/feature counts,
  and F4-9D PENDING/GO/NO_GO label;
- the layer toggle is disabled for archived geometry;
- users are directed to the dedicated F4 archive page.

For **web/f4-archive.html**:

- the saved Lucas–Kanade field-motion polygons remain directly visible as a
  purple archived layer;
- +15/+30 minute leads can be switched;
- a saved polygon can be selected to inspect target time, centroid, approximate
  projected area and research-object id;
- the older observed-origin / constant-motion point archive remains available
  as a separate optional layer rather than being mixed into the default view.

## Readability correction

The legacy archive screenshot showed enlarged dark marker strokes and oversized
yellow arrowheads after zoom. Root cause: marker radii/font sizes were
screen-compensated by 1/scale, but SVG strokes and filled arrowhead geometry
still scaled with the viewport.

The archive implementation therefore:

- uses non-scaling strokes for origin/end/city markers;
- computes arrowhead geometry inversely with zoom;
- keeps city-label font, offset and outline approximately constant in screen
  space;
- uses collision suppression for reference-city labels;
- defaults the cluttered legacy point layer to OFF.

## Scientific invariants

This addendum MUST NOT be interpreted as:

- removing an unfavorable historical F4 prediction;
- changing which prospective cases enter F4-9C;
- changing the F4-9D GO/NO_GO rule;
- changing prediction geometry or lead times;
- claiming the archived purple polygons are LPZ forecasts.

The same immutable public field-motion GeoJSON is retained. Only its placement
moves from the live map to the archive after staleness.

**Status:** implementation on isolated branch
`fix/f4-live-stale-archive-20260927`; local regression/browser acceptance
pending before main merge.
