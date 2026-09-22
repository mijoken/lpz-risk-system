# 2026-09-21 Fukushima/Miyagi F4 field-motion case: independent meteorological-structure audit

Opened 2026-09-22. Stage: **source-only audit completed from user's local frozen-case output**; NOT a forecast-verification result or LPZ confirmation.

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
- **79 eligible observed source components** at 22:00 JST (non-boundary, >=2-pixel >=30-mm/h class); **77 rendered components per horizon** in the public +15/+30 GeoJSON (154 display polygons total). A display-only ID comparison shows source IDs **1 and 2 are absent from BOTH public leads**, while IDs **3–79** occur at both leads. Whether the first two left the fixed domain, became empty after transport, or failed display-envelope construction is not established without inspecting the original source/forecast masks; do not silently treat 77 as the original eligible source count.
- Published 15-minute polygon-centroid range: 36.82285–40.86205 N, 140.73830–145.19821 E.
- Published 15-minute polygon component **pixel-area** statistics (approx km²; not total convex hull area): median **4.13**, upper quartile **7.38**, maximum **101.08**; **45/77** smaller than 5 km² and **0/77** individual components >=500 km².
- Published 30-minute pixel-area statistics: median **3.90**, maximum **121.17**; **44/77** smaller than 5 km² and **0/77** individual components >=500 km².
- Exploratory projected *polygon vertex* PCA ratios >=2.5: 12/77 at lead +15 min and 13/77 at lead +30 min. These vertex-derived convex-hull ratios are **NOT** the JMA 5-km grid three-hour 100-mm area long/short-axis test, **NOT** measurements of observed source rain objects, and are unstable for tiny components; do not use them as LPZ classification.
- Between the +15 and +30 display predictions, median displacement of corresponding projected centroids is approx **9.37 km per 15 min**. This is displacement **between two model-generated positions**, **not measured physical motion or verification skill**.

This pattern supports: a large **collection of scattered, mostly small >=30-mm/h component extrapolations** along/offshore of Fukushima/Miyagi, with some locally elongated display polygons. The screenshot does not by itself establish **one coherent, persistent mesoscale linear rainband**, nor convective regeneration/training or official LPZ-like 3-hour accumulation. Conversely, it is compatible with pre-existing heavy-rain conditions in the area and is an independently documentable event to examine further.

## Actual immutable local source-only result, supplied 2026-09-22

PowerShell command `audit_f4_20260921_source_structure.py --case-json D:/program/lpz-risk-system_f4_9c_cohort/cases/20260921T130000Z.json` completed and printed `SOURCE-ONLY AUDIT COMPLETE`. The frozen source NPZ SHA-256 matched both case and manifest:

`f851aa1e3ab90503f73ecf8d318af8328233d411efed304ae54bbcdc7cc4d7a1`

Source: **four existing observations at 21:45, 21:50, 21:55, and 22:00 JST**. Source area is fixed z8 mosaic origin (228,96), 16 tiles, east **140.625–146.25°E**, north **36.597889–40.979898°N**; parent z6 (57,24). This region extends from the Fukushima/Miyagi coast into the Pacific. The five largest retained observed source components have centroids ~**142.65–143.22°E, 37.55–37.88°N**, thus offshore rather than necessarily over the cities of Fukushima or Sendai.

| Observation JST | Public radar class pixels >=30 mm/h | >=50 mm/h | >=80 mm/h | unclassified pixels |
|---|---:|---:|---:|---:|
| 21:45 | 16,375 | 5,435 | 556 | 589,537 |
| 21:50 | 18,597 | 5,847 | 462 | 589,469 |
| 21:55 | 18,087 | 5,368 | 449 | 591,996 |
| 22:00 | 17,475 | 4,589 | 431 | 601,273 |

`>=N` counts are conservative discrete JMA public radar-class **instantaneous mm/h thresholds** (not measurements of accumulated rain). Unclassified pixels are **not** zero rain. The total fixed mosaic contains 1,048,576 pixels per frame.

Across all four observations, **7,125 pixel locations** were >=30 mm/h at all four times; **32,939** were >=30 at least once. `7125/32939=0.21631` is a **fixed-coordinate four-frame overlap fraction** over the 15-minute span. It does NOT mean “21.6% of storms persisted” or show 3-hour training of the same geographic region. Moving storms may reduce fixed-pixel overlap even when the rain system persists.

At 22:00, **79 non-boundary >=30-mm/h observed components of at least 2 pixels**:

- area median **4.608 km²**; largest **128.301 km²**; **0 components >=500 km²**;
- source-pixel morphology aspect-ratio median **1.512**, maximum **5.168**, **7/79 >=2.5**;
- largest five area/shape (km² / ratio): **128.301 / 1.942**, **108.538 / 3.397**, **62.097 / 1.735**, **47.053 / 5.168**, **43.018 / 1.998**;
- source-component coordinates represent selected *offshore* intense precipitation classes, not official LPZ danger locations.

### Audit interpretation, before any F4-9D outcome

**Confirmed:** an active, geographically plausible field of many >=30-mm/h precipitation-class objects in the Pacific off Fukushima/Miyagi, with >=50 and >=80 classes present, some elongated source objects, and >7,000 same-location >=30-class pixels across the 15-minute source interval.

**Not confirmed:** a single contiguous >=500-km² 3-hour high-accumulation rainband; LPZ formal criteria; continuous convective regeneration; which source component caused a particular observed on-land disaster; or accuracy of +15/+30 predictions. Also do not interpret absence of a >=500-km² *instantaneous* source object as definitive evidence against a 500-km² *three-hour accumulated rainfall* criterion: they are different phenomena and different calculations.

**Milestone class:** `REAL_EVENT_OFFSHORE_INTENSE_RAIN_OBJECT_CAPTURE_AND_PRECOMMITTED_MOTION_DISPLAY`. This is a genuine research observation/operational-output milestone, **not** `LPZ_DETECTED` or `LPZ_PREDICTED`. F4-9C / 9D remain frozen; no performance results were opened.

## Official definition caveat

The 2026 JMA LPZ occurrence product is based on >=100 mm in the preceding 3 hours over >=500 km² on a 5-km grid, a 2.5+ axial ratio, >=150 mm 3-hour peak, and relevant KikiKuru risk threshold criteria. The F4 research uses a conservative **instantaneous >=30 mm/h class threshold** on selected 5-minute public radar mosaics. Instantaneous mm/h is **not** a 3-hour mm accumulation, and a sum of tiny independent component footprints cannot substitute for the official 500 km² contiguous accumulated-rainfall area. Source: https://www.jma.go.jp/jma/kishou/know/bosai/kishojoho_senjoukousuitai.html

## Source-only follow-up (no F4-9C anti-peeking)

Code: `scripts/audit_f4_20260921_source_structure.py`, audit branch `audit-20260921-kanto-vs-f4-display`.

Input **only** `D:/program/lpz-risk-system_f4_9c_cohort/cases/20260921T130000Z.json` and its referenced `source_archive_dir/manifest.json` + `decoded_field.npz`.

The script verifies frozen source SHA-256 and case/source mosaic identity; reads exactly **four observed source radar frames at 5-minute spacing** (only 15 minutes total) and reports >=30/50/80-mm/h categorized pixel counts, same-*fixed-pixel* four-frame overlap, eligible observed component areas/shapes and coverage. It cannot determine 3-hour training, later rain, LPZ formal classification, or F4-9C forecasting skill.

**After source-only results:** multiple intense source objects and some elongated morphologies are confirmed; a coherent LPZ-like mesoscale system and the skill of its motion forecast remain unconfirmed. Preserve the frozen F4-9C / F4-9D protocol regardless of outcome.


## Next validation: 3-hour source-data availability gate (in progress)

The preceding source-only morphology proof covers **21:45–22:00 JST**.
Do not infer 3-hour organization from its four five-minute snapshots.

Available-repository checks on 2026-09-22:

- `research/prospective/2026/09/` contained canonical derived-feature
  archives only through **2026-09-20 UTC** at audit time; no 2026-09-21
  canonical daily archive was yet in the inspected main tree. The O8.1-D
  archive policy states `raw_radar_archived=false` and
  `raw_grib_archived=false`. A later completed daily archive would
  not retrospectively become a raw 5-minute radar movie.
- The measured public JMA radar metadata retention window on
  2026-09-21 04:48 UTC was **180 minutes**; the audited safe catch-up
  policy was **120 minutes**. This is not a perpetual historical radar
  API and should not be assumed to supply 2026-09-21 19–22 JST
  on the following day.
- Historical 3-hour polygon-pilot code uses source-native **2023**
  development GSMaP/IMERG samples, not this 2026 event.
- NASA IMERG **Late Run** typically takes ~14 h from observation, whereas
  **Final Run** normally takes ~3.5 months. Do not substitute Final
  until actual 2026-09-21 granules are verified, nor silently substitute
  Late for Final. Official source:
  https://gpm.nasa.gov/resources/faq/what-determines-latency-imerg
- JAXA hourly Gauge Standard v8 was previously proven accessible for
  2023, but 2026-09-21 specific Standard payload availability has
  **not** been checked. A potential NRT product is a different source,
  to be labeled and decoded separately if used.

The next immediate task is **metadata-only inventory of already-captured
local F4-9A source archives**, without opening F4-9C future
observations/verifications or downloading anything:

`scripts/audit_f4_20260921_3h_source_availability.py`

Required event-window metadata coverage is **19:00–22:00 JST**
(`2026-09-21T10:00:00Z` through `13:00:00Z`) at **37 inclusive
five-minute timestamps** on the same fixed z8 mosaic
`(zoom=8, origin_tile_x=228, origin_tile_y=96, tile_count=16)`.
Different source mosaics must remain separate.

Even if 37 timestamps and their source files exist, the public
HRPN categorical rate fields cannot be claimed to reconstruct exact
JMA 5-km three-hour analyzed rainfall or official LPZ issuance. They
can support an explicitly labeled **same-grid 3-hour categorical
strong-rain persistence/organization descriptor**, conditional on
source bytes/unknown-pixel handling; independent 3-hour accumulation
requires suitable source-native actual rainfall granules.

**Local metadata census result (2026-09-22):** same-mosaic F4-9A archives exist at source slots 21:30, 21:45 and 22:00 JST. After deduplicating overlapping four-frame archives, there are **10 unique five-minute timestamps** covering **21:15–22:00 JST**. The full 19:00–22:00 JST requirement is **10/37**, with 27 earlier timestamps missing; all three referenced source NPZ files exist. The two duplicate frame timestamps are expected archive overlap, not corruption. Therefore exact local same-mosaic 3-hour radar reconstruction is unavailable from the frozen F4 source store.

**Next source-only gate:** analyze only the contiguous 45-minute 10-frame window with `scripts/audit_f4_20260921_45min_source_organization.py`. It verifies SHA-256, duplicate-frame equality, and reports source-only >=30/50/80 class intensity, component morphology, whole-field PCA geometry, and fixed-coordinate persistence restricted to pixels classified at all 10 frames. This remains **45-minute categorical radar organization**, not 3-hour accumulation, LPZ occurrence classification, or forecast verification.

**45-minute source organization result (completed 2026-09-22):** the three overlapping immutable source archives decode identically at duplicate timestamps 21:30 and 21:45 JST. Ten unique five-minute source frames cover 21:15–22:00 JST on fixed z8 mosaic (228,96), with no future observations or verification outputs opened.

Across the ten frames, >=30-mm/h class pixel counts remain 16,002–18,597; >=50 remain 2,918–5,847; >=80 remain 73–556. Whole-field >=30 morphology has PCA aspect ratio **3.154–5.392 at every frame** and orientation **33.379–38.116 degrees clockwise from north**, a narrow ~4.74-degree orientation spread across the full 45 minutes. This is substantially more consistent with a persistent linear organization axis than with unconstrained random orientation, while still not proving JMA LPZ criteria.

The 45-minute known-all-frame >=30 swept union contains 56,152 pixels and 368 connected components. The largest connected union component contains **40,934 pixels = 72.9% of the swept union**, providing an additional cohesion indicator despite many small fragments. The swept-union PCA aspect ratio is **3.9965**, orientation **34.09 degrees**. Fixed-coordinate >=30 occurrence among the 56,152 any-time pixels is: >=3/10 frames **24,489 (43.61%)**; >=5/10 **12,774 (22.75%)**; >=8/10 **5,055 (9.00%)**; all 10 **2,112 (3.761%)**. Fixed-coordinate persistence is conservative for moving rain systems and is restricted to pixels scientifically classified at all ten frames.

Observed source component summaries fluctuate strongly: some frames contain very large eligible connected >=30 components (>1,600–2,260 km²), while adjacent frames can fragment below ~200 km². Because 8-connectivity can merge/split through narrow pixel bridges and boundary-truncated components are excluded, those component-area jumps must not be interpreted literally as physical rainband growth/collapse without object-level tracking. The more robust descriptive signal here is the stable whole-field axis plus the dominant connected swept corridor.

**Audit classification after 45-minute source analysis:** `PERSISTENT_LINEARLY_ORGANIZED_INTENSE_RAIN_FIELD_45MIN_SUPPORTED`. This means the pre-existing observed field had a stable linear organization axis and intense >=30/50/80 classes before the published motion extrapolation. It does **not** mean `JMA_LPZ_OCCURRED`, `LPZ_GENESIS_PREDICTED`, or that F4-9B forecast skill has been established. Because the purple product advects an already-observed >=30 field, the defensible milestone is **detection plus precommitted short-time projection of a real organized intense-rain field**, not prediction of its original genesis.

**State: local exact 3-hour radar source coverage FAIL (10/37); 45-minute organization SUPPORTED; independent source-native 3-hour accumulation confirmation is the next audit.**
