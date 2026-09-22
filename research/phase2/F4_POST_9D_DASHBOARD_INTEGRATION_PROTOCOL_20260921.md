# Post-F4 Field-Motion Research Dashboard Integration Protocol — 2026-09-21

## Purpose

This protocol fixes the display policy for the F4-9B Lucas-Kanade /
semi-Lagrangian research model before the F4-9C prospective outcome is opened.

The dashboard publication decision is intentionally independent from the F4-9D
scientific GO / NO-GO decision.

## Frozen display rule

The field-motion model is displayed on the research dashboard regardless of
whether F4-9D returns GO or NO-GO.

F4-9D changes only the research-decision label:

- PENDING: prospective validation is still running;
- GO: the frozen F4-9D criteria passed;
- NO-GO: the frozen F4-9D criteria did not all pass.

GO / NO-GO must never alter the already-generated geometry for the same source
case.

## Research-only semantics

The public field-motion product must always retain all of the following:

- research_only = true
- validated_forecast = false
- production_integration_enabled = false
- risk_engine_allowed = false
- official_risk_output = false
- lpz_forecast_generated = false
- probability_generated = false
- severity_generated = false

The dashboard must not call this an LPZ probability, risk, warning, or official
forecast.

## Map presentation

The existing F4-4 constant-motion research envelope remains available.

The field-motion model is a separate map layer:

- model: Lucas-Kanade dense field motion;
- extrapolation: frozen semi-Lagrangian F4-9B mechanics;
- horizons: +15 and +30 minutes from prospective as-of;
- source: latest frozen prospective case;
- coverage: selected fixed z8 mosaic, not nationwide.

The two research layers are intentionally not merged because they represent
different research methods.

## Geometry

Each field-motion display feature is built from one frozen F4-9C source
component transported by the frozen F4-9B field-motion model.

Display geometry is a geographic convex hull of the transported component's
pixel cells. It is an envelope, not an exact future precipitation contour.

## Staleness and history

F4-4 live candidate envelopes remain freshness-gated; stale F4-4 live geometry
is suppressed and the fixed F4 archive remains available.

F4-9C field-motion envelopes are immutable historical research predictions.
When the source as-of exceeds the freshness limit, mark the F4-9C public
product ARCHIVED, retain its geometry for interactive research, and display its
source as-of prominently. Never imply that an archived projection is a current
forecast. This allows the finished F4 experiment to remain inspectable after
prospective collection stops.

## F4-9D independence

The publisher may read the F4-9D terminal artifact only to obtain the label
PENDING / GO / NO-GO.

It must not:

- change component membership;
- change forecast masks;
- change geometry;
- change lead times;
- retune the model;
- hide the model because of NO-GO.

## Completion condition

The dashboard integration is complete when:

1. the public product contract is tested;
2. the map has an independent field-motion layer toggle;
3. the research panel displays model, as-of, lead/count, selected geometry, and
   F4-9D label;
4. locked Risk Engine semantics are preserved;
5. a real frozen F4-9C artifact can be published into the same contract without
   UI code changes.

The frozen prospective source forecast may be published before F4-9D with
decision=PENDING, strictly without reading verification metrics. Following
F4-9D the same display path may update the label to GO or NO-GO; neither
outcome removes the archived geometry. A dedicated isolated local publication
worktree may push display-only GeoJSON to GitHub Pages, without changing the
dirty research main worktree or Scheduled Task.
