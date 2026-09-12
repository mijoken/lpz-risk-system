# LPZ Public Web UI Requirements

Status: deferred UI refinement requirements captured after Phase 2L-O3 first successful map render.

These requirements are part of the public GitHub Pages product direction and should be reviewed before future UI work.

## Confirmed after first successful render

The Phase 2L-O3 prototype successfully rendered all 142 JMA primary subdivisions, but the current visual scale is too small for comfortable public use.

### Typography
- Increase the base font size across the page.
- Increase card/status text sizes and spacing.
- Maintain readable typography on both desktop and mobile.
- Avoid shrinking explanatory text merely to fit more content above the fold.

### Map sizing
- Make the Japan map substantially larger on desktop.
- Give the map priority over secondary status cards when screen width is limited.
- Use a responsive layout so the map remains prominent on tablets and phones.

### Interactive navigation
Desktop requirements:
- Mouse-wheel zoom centered near the pointer position.
- Click-and-drag pan.
- A reset/home control to return to the nationwide view.

Mobile/touch requirements:
- Pinch-to-zoom.
- One-finger/touch pan after zooming.
- Responsive touch targets and no accidental page scrolling while manipulating the map.

### Region interaction
- Preserve hover behavior on desktop.
- Provide tap/click selection on touch devices where hover does not exist.
- Show JMA primary-subdivision name and code clearly at the selected region.

### Scientific/publication guardrail
Until frozen validation is completed and the Risk Engine is explicitly released:
- do not show LPZ probability,
- do not show warning-level colors,
- do not imply that geographic styling is a validated risk heat map.

The current map remains a geographic/operational layer only.

## Implementation priority

These requirements are intentionally deferred until after the initial end-to-end public data pipeline is working. They should be implemented as a dedicated UI refinement phase rather than blocking O4/O5 production plumbing.
