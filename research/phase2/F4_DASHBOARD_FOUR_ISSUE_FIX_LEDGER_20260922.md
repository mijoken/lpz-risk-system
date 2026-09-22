# F4 Dashboard — Four-Issue Fix Ledger (2026-09-22)

This ledger tracks the four defects reported from user screenshots. Do not
declare the work complete from a successful commit alone; close only after
local regression tests, GitHub Pages success and a browser check.

## 1. Empty research panels / apparent inactivity

- F4-4 yellow candidate envelopes are freshness-gated. When too old, clearly
  explain that there are no *currently selectable* yellow shapes and link to
  the fixed archived F4 research below the map.
- F4-9C purple research can be published before 9D as PENDING from frozen case
  plus frozen component-forecast NPZ, without reading outcome/verification data.
- For a source older than 90 minutes, keep the purple geometry but visibly
  mark it as ARCHIVED, not as a current forecast. Browser must recompute age.
- Fail if NPZ SHA-256 does not match the frozen F4-9C case.

## 2. Research feature selection does not work

- Remove root SVG pointer capture at pointerdown in the main map and archived
  map: it can retarget the click away from interactive child geometry.
- When a layer is empty or stale-suppressed, do not instruct users to select a
  nonexistent yellow/purple shape.
- Browser acceptance: click visible purple/yellow shape and check detail panel;
  in fixed archive click numbered point and side-list button.

## 3. Blank space below the main live map

- Move fixed F4 research summary into the map column beneath the rain console,
  next to the full-height research/status sidebar, instead of below the entire
  two-column dashboard.
- Single-column responsive order: map, fixed F4 research, sidebar.
- Browser acceptance: no excessive blank map-column gap above F4 summary.

## 4. Archived F4 link, static-vs-live labeling and corrupted visual layout

- The link opens a *fixed* historical source run 35564667965, not a live feed.
  Explicitly label this and retain the historical data.
- Remove CSS font-size overrides that stop SVG attributes from shrinking city
  labels and object numbers on zoom.
- Show reference-city labels only in view, after min-scale and screen-space
  collision checks; retain dots.
- Split the selected object's multiline text into readable metric cards.
- Browser acceptance: text does not explode over the map at 5x–20x zoom and
  clicking the archive origin/select-list updates the cards.

## Publication route and guardrails

The one-shot script `scripts/publish_f4_field_motion_from_local.ps1` operates
on a dedicated clean worktree. It reads the local frozen F4-9C cases and NPZ;
it never reads F4-9C verification rows, changes the cohort, reruns the model,
uses the dirty development web files, edits Scheduled Tasks or unlocks Risk.

First run without `-Push` for a dry run. Push only after counts and research
lock checks pass. GitHub Pages success and browser verification are separate
required closing evidence.

## Tests

- tests/test_publish_f4_field_motion_research.py
- tests/test_field_motion_dashboard_contract.py
- tests/test_f4_archive_ui_regression.py
- tests/test_publish_latest_f4_geographic_research.py
- tests/test_public_web.py
- node --check web/js/app.js, web/js/map.js, web/js/f4-archive.js
- PowerShell Parser.ParseFile on the one-shot local publisher

## Status

Implementation on isolated branch. Remaining: local tests, main FF, local
read-only publication proof then explicit push, Pages verification, screenshots.
F4-9C/9D model and terminal decision remain unchanged.
