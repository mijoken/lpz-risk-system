# LPZ forecast product north star — binding project requirement

Status: **permanent user requirement, 2026-09-21**. Read this before any new LPZ feature, F4/F5 research plan, dashboard work, or chat handover. This document overrides a tendency to treat technical counters or F4 point tracking as the product. Preserve existing scientific release gates and frozen confirmatory work.

## The actual user question

**Where, when, how large, how intense, how likely, and how is a linear precipitation band developing?**

The intended nationwide, automatically generated, map-first forecast must answer in Japanese, with **no manual region selection**:

| Forecast field | Required human-facing presentation |
| --- | --- |
| Region | e.g. eastern Kanagawa–southern Tokyo; geographic names from a validated geographic join |
| Center | latitude / longitude |
| Time | forecast start/end and issue time, with time zone |
| Footprint | direction, length and width, on map |
| Intensity | forecast rainfall amount and accumulation period |
| Probability | calibrated probability and forecast horizon |
| Affected places | municipalities/regions spatially joined to the forecast footprint |
| Development | forming / maintaining / weakening, with defined evidence |

**Illustrative mock-up ONLY, never an actual forecast:** eastern Kanagawa–southern Tokyo; 35.45 N, 139.65 E; 16:30–18:00; southwest–northeast 80 km × 15 km; 80–100 mm/h; 65%; Yokohama/Kawasaki/Ota; forming. Do not copy these example numbers or names into data, dashboards, tests masquerading as measured outputs, or alerts.

## Required map layers and development order

1. Show **actual observed** radar precipitation objects at their actual lat/lon, valid time, location and observed geometry; label an observed bounding box as a box, never an actual rainfall polygon.
2. Overlay **research-only** F4 15/30-minute projected centroid points and arrows from their observed origins; where independently available, overlay exact-time observed outcomes, and visibly distinguish verified algorithmic identity from nearest-object proximity or unresolved tracking.
3. Develop, test and validate precipitation-band genesis, repeated upstream initiation, persistence, footprint/length/width, intensity, lead time, affected regions and calibrated probability. Only after relevant evidence and release gates may these be shown as LPZ forecasts.

F4 currently extrapolates **points only** in a selected fixed radar mosaic; it is neither a nationwide uniformly sampled forecast nor an LPZ genesis/footprint/intensity/probability predictor. Its archived aggregate metrics (1,536 objects, 106 projected, 58 comparable, 6 identity-matched, 52 unresolved) are **developer diagnostics**, not the product and not a forecast skill certificate. Do not spend further iterations adding aggregate-only cards instead of making geography visible. Six identity-matched projections are too few to claim operational location skill.

## Publication contract

- Keep NOW observed rain, archived research, experimental evidence and released FORECAST clearly separate. No false LPZ warning/probability, invented place name, fabricated forecast polygon, or risk-colored map.
- Missing information must read **not yet available / not validated**, never be filled with a plausible example.
- Preserve locked Risk Engine, frozen 2025 Primary/K2 confirmatory validation and C3 prospective research. Never let retrospective research unlock them.
- Do not conflate JMA official alerts with this system's own forecasts. JMA official current-alert integration was requested **after the F4 geographic research visualization milestone**, not as a replacement for it.
- The user's local dirty UI/GFS changes are not disposable. Never reset, clean, stage or commit them implicitly; GitHub is the code/evidence source of truth, and use targeted paths only.
- Avoid repeated inventories, acquisition, artifact downloads and already completed audits. Reuse archived O8.1 artifacts and existing F3/F4 derivatives. Next concrete priority: **georeferenced archived F4 research map**; then expand coverage and validated band prediction.
