# F4-9B Field-Motion Specification Freeze — 2026-09-21

## Purpose

Freeze one and only one field-level short-time motion model before F4-9C prospective evaluation.
F4-9B is a mechanics/specification stage. It does not evaluate forecast skill.

## Frozen model

- Input: one F4-9A decoded field archive.
- Exactly four JMA HRPN z8 class-index fields at 5-minute spacing.
- Motion family: Lucas–Kanade local feature tracking with dense IDW interpolation.
- Reference behavior/parameters: pySTEPS 1.21.5 Lucas–Kanade defaults.
- Implementation: LPZ local research implementation so Windows does not require building pySTEPS Cython extensions.
- Forecast transport: local semi-Lagrangian implementation aligned to pySTEPS mechanics.
- Leads: +15 and +30 minutes only.
- Mandatory baseline: Eulerian persistence.
- No alternative motion algorithm is allowed during F4.

## Motion-input encoding

Optical flow receives a categorical image signal only:

- JMA class_index -1 -> signal 0;
- JMA class_index 0..7 -> signal 1..8.

This encoding has no physical rainfall meaning. Signal 0 must not be described as 0 mm/h, and values 1..8 must not be described as rainfall intensities.
No class midpoint or continuous mm/h reconstruction is allowed.

The actual forecast event remains the conservative definite >=30 mm/h mask from JMA classes 5, 6, and 7.

## Frozen Lucas–Kanade parameters

Shi–Tomasi feature detection:
- max_corners = 1000
- quality_level = 0.01
- min_distance = 10
- block_size = 5
- buffer_mask = 5
- use_harris = false
- k = 0.04

LK feature tracking:
- winsize = [50, 50]
- nr_levels = 3
- criteria = [3, 10, 0]
- flags = 0
- min_eig_thr = 1e-4

Dense-field cleanup/interpolation:
- nr_std_outlier = 3
- k_outlier = 30
- size_opening = 3
- decl_scale = 20
- IDW power = 0.5
- IDW k = 20
- IDW distance offset = 0.5 pixel

## Frozen semi-Lagrangian parameters

- timesteps = [3, 6]
- lead minutes = [15, 30]
- vel_timestep = 1 radar interval
- n_iter = 1
- velocity interpolation order = 1
- event-mask interpolation order = 0
- outside-domain event value = 0
- binary decode threshold = 0.5

The 0.5 decode is numerical only: nearest-neighbor transport is categorical and this is not a meteorological threshold.

## Frozen research environment

Production pyproject is unchanged. F4-9B runs in a separate research venv with:

- numpy 2.4.6
- scipy 1.17.1
- opencv-python-headless 4.14.0.94
- pytest 9.1.1 (test runner only)

Executable artifacts:

- config/f4_9b_field_motion_spec.json
- src/lpz_risk/f4_field_motion.py
- scripts/run_f4_9b_field_motion.py
- research/requirements/f4_9b_field_motion.txt
- tests/test_f4_9b_field_motion_spec.py

## F4-9B completion rule

F4-9B ends when one existing F4-9A archive passes the frozen mechanics proof:

1. exact specification tests pass;
2. frozen runtime versions match;
3. velocity output shape is (2, H, W);
4. forecast and persistence output shapes are (2, H, W);
5. +15/+30 leads only;
6. output SHA-256 is recorded;
7. future observations are not read;
8. forecast skill is not scored;
9. parameter tuning is false;
10. all Risk Engine / probability / severity / validated-forecast locks remain false.

After this proof, no F4-9B model or parameter change is permitted.

## F4-9C and F4-9D

F4-9C uses only the frozen F4-9B implementation. Collection stops at 100 exact future comparisons with at least 3 distinct collection slots/events, or after 14 eligible calendar days, whichever occurs first.

Primary endpoint: paired best-IoU delta (field-motion minus persistence), separately at +15 and +30 minutes.
Secondary endpoints: any-overlap rate, median nearest >=30 mm/h component-centroid distance, and technical/missing-frame rate.

F4-9D applies the already frozen GO/NO-GO rule. No retuning, second model, area/speed gate, or post-hoc rescue is permitted.

Regardless of result, F4 closes at F4-9D.
