# Phase 0 research log

## 2026-09-09 — Source policy frozen

Decision:
- Proceed with a no-paid-API v0.1 acquisition proof.
- Keep official JMA LPZ forecast products outside the independent risk score.
- Split live and historical pipelines.
- Require evidence from GitHub Actions before a source is promoted to operational CORE.
- Do not invent undocumented machine endpoints; mark them `PENDING` until verified.

Next:
1. Run the Phase 0.5 workflow.
2. Inspect per-source evidence.
3. Convert JMA rasrf from metadata proof to actual raster payload proof.
4. Convert GFS from service proof to actual Japan-subset GRIB2 proof.
5. Verify stable WINDAS machine acquisition.
6. Verify Himawari image/channel payload.
7. Accumulate repeated-run availability statistics.
