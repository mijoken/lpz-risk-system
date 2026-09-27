# Dashboard Main-Column Gap Fix — 2026-09-27

## Problem

The public live page showed a very large vertical blank region between the
live-precipitation panel and the archived F4 research panel.

The cause was structural CSS Grid coupling:

```
"map      side"
"research side"
```

The right-side column spans both grid rows. Because that sidebar is much taller
than the map, the shared row sizing produced a large vertical gap before the
left-side research panel.

## Fix

The left side is now one independent vertical stack:

```
dashboard
├─ dashboard-main
│  ├─ map-panel
│  └─ research-panel
└─ side
```

`.dashboard-main` owns its own 18 px vertical gap, so the research panel
follows immediately after the live map regardless of sidebar height.

Responsive behavior remains:

- desktop: main stack + side column;
- <=1100 px: main stack then side stack;
- <=760 px: existing single-column side layout.

The stylesheet URL is versioned for this release so browser cache cannot retain
the previous grid structure during verification.

## Scientific scope

Layout-only change. No map data, F4 geometry, model output, F4-9C/F4-9D
criteria, risk lock, or research state is modified.

## Local static validation — 2026-09-27

User executed the isolated worktree at commit
`f4bd10893b6e8c4d9efc7e5fb459c569ff4fff11`.

Evidence:

- worktree HEAD matched the expected remote branch HEAD;
- Python import resolved `lpz_risk` from
  `D:\\program\\lpz-risk-system_ui_gap_test\\src\\lpz_risk`;
- dashboard regression suite: **31 passed**;
- `node --check` passed for `web/js/map.js`, `web/js/app.js`, and
  `web/js/f4-archive.js`.

The first validation attempt exposed only a test-selector defect:
the HTML correctly uses `class="panel map-panel"`, while the test searched for
the exact nonexistent substring `class="map-panel"`. The test was corrected
without changing production HTML/CSS behavior.

**Status:** implementation PASS; static validation PASS; browser acceptance
pending before merge.
