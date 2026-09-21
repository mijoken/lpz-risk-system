# F4-9B Field-Motion Specification Freeze — 2026-09-21

## Purpose

Freeze one and only one field-level short-time motion model before the F4-9C prospective head-to-head cohort is inspected.

This stage is a mechanics/specification stage. It does **not** evaluate forecast skill.

## Frozen model

- Input: one F4-9A decoded field archive.
- Frames: exactly four JMA HRPN z8 class-index fields at 5-minute spacing.
- Motion estimation: pySTEPS 1.21.5 Lucas–Kanade dense motion.
- OpenCV runtime: opencv-python-headless 4.14.0.94.
- All four input frames are used.
- Input values remain JMA precipitation class indices. No class midpoint or continuous mm/h reconstruction is allowed.
- Pixels with class_index < 0 are masked during optical-flow estimation.
- The forecast field is the latest-frame binary mask for intervals definitely >=30 mm/h, i.e. JMA class indices 5, 6, and 7.
- Forecast transport: pySTEPS semi-Lagrangian extrapolation.
- Leads: +15 and +30 minutes only.
- Velocity timestep: one 5-minute radar interval.
- Interpolation order: nearest-neighbor (0) so the advected event mask remains categorical.
- Outside-domain value: 0 for the predicted >=30 mm/h event mask.
- Mandatory baseline: Eulerian persistence of the same latest definite >=30 mm/h mask.

The exact executable contract is stored in:

- config/f4_9b_field_motion_spec.json
- scripts/run_f4_9b_field_motion.py
- research/requirements/f4_9b_field_motion.txt

## Explicit Lucas–Kanade parameters

The following values are frozen and must match exactly:

- fd_method = shitomasi
- interp_method = idwinterp2d
- dense = true
- nr_std_outlier = 3
- k_outlier = 30
- size_opening = 3
- decl_scale = 20
- lk_kwargs = null
- fd_kwargs = null
- interp_kwargs = null
- verbose = false

No alternative optical-flow method is allowed during F4.

## Explicit extrapolation parameters

- timesteps: [3, 6]
- lead minutes: [15, 30]
- vel_timestep = 1
- outval = 0.0
- allow_nonfinite_values = false
- n_iter = 1
- interp_order = 0
- return_displacement = false
- numerical categorical decode threshold: 0.5

The decode threshold is only a numerical conversion of nearest-neighbor 0/1 transport output. It is not a meteorological threshold and must not be tuned.

## F4-9B completion rule

F4-9B is complete when all of the following are true:

1. the specification JSON passes its exact-contract tests;
2. the isolated research environment contains the frozen dependency versions;
3. one existing F4-9A archive can be processed end-to-end;
4. output shapes are exactly velocity (2,1024,1024), forecast masks (2,1024,1024), and persistence masks (2,1024,1024) for the current geometry;
5. output is immutable and SHA-256 recorded;
6. no future observation is read;
7. no skill score is calculated;
8. all Risk Engine / LPZ probability / severity / validated-forecast locks remain false.

Once these are satisfied, the implementation and parameters are frozen for F4-9C.

## F4-9C prospective evaluation

F4-9C may use only the frozen F4-9B implementation.

Stop when:

- 100 exact future comparisons are available across the two lead horizons and at least 3 distinct collection slots/events contribute, or
- 14 calendar days of eligible prospective collection have elapsed,

whichever occurs first.

Primary endpoint:

- paired best-IoU delta = optical-flow advection minus Eulerian persistence, reported separately for +15 and +30 minutes.

Secondary endpoints:

- any-overlap rate;
- median nearest observed >=30 mm/h component centroid distance;
- technical/missing-frame rate.

No parameter tuning, area/speed gate, second optical-flow algorithm, or post-hoc rescue rule is allowed.

## F4-9D terminal decision

GO only when every condition in config/f4_9b_field_motion_spec.json is satisfied.

Otherwise: **NO-GO and close F4.**

Regardless of outcome, F4 ends at F4-9D.
