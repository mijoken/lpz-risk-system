# 2026-09-21 Fukushima/Miyagi F4 field-motion case: independent meteorological-structure audit

Opened 2026-09-22. Stage: **source-only confirmation pending**, not a forecast-verification result.

## Question and precommitted interpretation rule

The user asks whether the purple Lucas–Kanade research footprint during the 2026-09-21 evening Tohoku rain event was an early indication of a linearly organized heavy-rain system, even though no JMA official LPZ occurrence alert was established for the case.

Before looking at the frozen source-only morphology, distinguish:

1. selection of >=30 mm/h observed radar-class components;
2. motion extrapolation of those components +15/+30 min from as-of;
3. temporally sustained narrow intense rainband;
4. official JMA LPZ occurrence criteria (three-hour accumulations, 5-km grid shape/area, peak 150 mm, and risk conditions);
5. prospective forecast skill against later observation.

Only (1) and (2) are available in the published F4 field-motion GeoJSON. The extra source-only audit script will check (1) at four pre-capture frames; it **never** examines (5).

## Event-time independent meteorological evidence

- At 2026-09-21 05:53 JST, Fukushima Local Meteorological Office warned of very heavy rain in Nakadori and Hamadori during Typhoon 25. Source: https://www.fukushima-tv.co.jp/bosai/extra/20260920205324_0_VPFJ50_070000.html
- At 2026-09-21 16:40 JST, a Japan Weather Association Tohoku-branch forecaster described Fukushima/Miyagi as the rain center, observed accumulated rain >100 mm by then in parts of Iwaki, and forecast the rainy peak around night to midnight. This **is not 3-hour accumulated rain at 22:00**: https://tenki.jp/forecaster/motoasa/2026/09/21/40696.html
- At 2026-09-21 21:50 JST, Weathernews reported that Kanto's rain peak was receding and Typhoon 25 was to the east of Choshi, moving NE. This supports the evening case being a different time/meteorological context from Kanto's early afternoon alert, NOT a proof of Tohoku LPZ occurrence: https://weathernews.jp/news/202609/210371/
- The 22:00 JMA typhoon position transcribed at 22:20/22:45 by TBC was 35.1N, 142.1E, NE 35 km/h, 960 hPa: https://newsdig.tbs.co.jp/articles/tbc/2961395?display=1

**Correction to potential milestone claim:** Fukushima and Miyagi were **not unmonitored** by JMA/forecasters. An isolated official LPZ imminence/occurrence alert for the *specific offshore rain structures* has not been verified. Regional rain alerts and LPZ-specific alert status are different questions.

## Frozen public F4 geometry (descriptive ONLY)

Exact source: `web/data/research/f4_field_motion_research.geojson` at commit `133387e1a4648ed136a8d4904afb58219cd0cb90`.

- Frozen case `20260921T130000Z`, source radar slot **2026-09-21 22:00 JST**, prospective as-of **22:15 JST**; targets **22:30/22:45 JST**.
- The frozen F4-9B source observation leads are +30/+45 minutes because the source is already 15 minutes behind the as-of. Do **not** describe 22:30 as “15 minutes after the last observed source.”
- 77 eligible source components, 77 15-minute and 77 30-minute display polygons.
- Published 15-minute polygon-centroid range: 36.82285–40.86205 N, 140.73830–145.19821 E.
- Published 15-minute polygon component **pixel-area** statistics (approx km²; not total convex hull area): median **4.13**, upper quartile **7.38**, maximum **101.08**; **45/77** smaller than 5 km² and **0/77** individual components >=500 km².
- Published 30-minute pixel-area statistics: median **3.90**, maximum **121.17**; **44/77** smaller than 5 km² and **0/77** individual components >=500 km².
- Exploratory projected *polygon vertex* PCA ratios >=2.5: 12/77 at lead +15 min and 13/77 at lead +30 min. These vertex-derived convex-hull ratios are **NOT** the JMA 5-km grid three-hour 100-mm area long/short-axis test, **NOT** measurements of observed source rain objects, and are unstable for tiny components; do not use them as LPZ classification.
- Between the +15 and +30 display predictions, median displacement of corresponding projected centroids is approx **9.37 km per 15 min**. This is displacement **between two model-generated positions**, **not measured physical motion or verification skill**.

This pattern supports: a large **collection of scattered, mostly small >=30-mm/h component extrapolations** along/offshore of Fukushima/Miyagi, with some locally elongated display polygons. The screenshot does not by itself establish **one coherent, persistent mesoscale linear rainband**, nor convective regeneration/training or official LPZ-like 3-hour accumulation. Conversely, it is compatible with pre-existing heavy-rain conditions in the area and is an independently documentable event to examine further.

## Official definition caveat

The 2026 JMA LPZ occurrence product is based on >=100 mm in the preceding 3 hours over >=500 km² on a 5-km grid, a 2.5+ axial ratio, >=150 mm 3-hour peak, and relevant KikiKuru risk threshold criteria. The F4 research uses a conservative **instantaneous >=30 mm/h class threshold** on selected 5-minute public radar mosaics. Instantaneous mm/h is **not** a 3-hour mm accumulation, and a sum of tiny independent component footprints cannot substitute for the official 500 km² contiguous accumulated-rainfall area. Source: https://www.jma.go.jp/jma/kishou/know/bosai/kishojoho_senjoukousuitai.html

## Source-only follow-up (no F4-9C anti-peeking)

Code: `scripts/audit_f4_20260921_source_structure.py`, audit branch `audit-20260921-kanto-vs-f4-display`.

Input **only** `D:/program/lpz-risk-system_f4_9c_cohort/cases/20260921T130000Z.json` and its referenced `source_archive_dir/manifest.json` + `decoded_field.npz`.

The script verifies frozen source SHA-256 and case/source mosaic identity; reads exactly **four observed source radar frames at 5-minute spacing** (only 15 minutes total) and reports >=30/50/80-mm/h categorized pixel counts, same-*fixed-pixel* four-frame overlap, eligible observed component areas/shapes and coverage. It cannot determine 3-hour training, later rain, LPZ formal classification, or F4-9C forecasting skill.

**Until the local source-only result is returned, do not upgrade the status from `CANDIDATE_MORPHOLOGY_TO_INVESTIGATE` to an independently confirmed LPZ-like rainband.** Preserve the frozen F4-9C / F4-9D protocol regardless of outcome.
