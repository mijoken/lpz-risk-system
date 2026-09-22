# 2026-09-21 Kanto rainfall vs F4 display — evidence audit, independent of F4-9C verification

Audit opened: 2026-09-22 JST. This is a **descriptive event/display alignment audit**, not a forecast-skill test or new F4 research stage. It must not read `D:/program/lpz-risk-system_f4_9c_cohort/verifications/`, any interim aggregate skill, or modify the frozen F4-9C/9D methodology.

## Question

A user observed a JMA linear-rainband advisory for Kanto on 2026-09-21, while the live research dashboard's archived purple F4-9B/9C Lucas–Kanade shapes were concentrated around northern Ibaraki/Fukushima/Tohoku and offshore. Determine whether this is a missed Kanto LPZ forecast, a source-coverage/timing mismatch, a threshold discrepancy, or a display misunderstanding.

## Official-information classification (JST)

| JST | Region | Evidence | Type |
| --- | --- | --- | --- |
| 2026-09-20 22:59 | Kanto-Koshin/Tokai | FNN transcription of JMA half-day outlook for 2026-09-21 | **Half-day forecast** of possible occurrence, not confirmed occurrence |
| 2026-09-21 06:11 and 16:44 | Saitama | Saitama prefectural archived Kumagaya Local Meteorological Office bulletins | **Forecast/caution** that a band may occur |
| 2026-09-21 12:19 | Northern Izu Islands | FNN contemporaneous alert | **2–3-hour imminence forecast** |
| 2026-09-21 12:58 | Eastern Kanagawa | Kawasaki City emergency chronology; corroborated by FNN contemporaneous alert | **2–3-hour imminence forecast** |
| 2026-09-21 18:00 | Chiba | Chiba Prefectural Disaster Portal local JMA commentary | **Forecast/caution** that a band may occur |
| 2026-09-21 14:25 | Yokohama | Weathernews states 53.0 mm in preceding 1 h ending 14:25 | **Observed intense rain**, NOT sufficient on its own to label a JMA linear rainband occurrence |

The definitive date/region/time of any **JMA occurrence notification** for 2026-09-21 Kanto is **UNVERIFIED**. Do not infer that it did not happen. The official JMA public incident list visible during audit had last update 2026-07-17, so the absence of a 2026-09-21 record there is NOT negative evidence. The distinction is especially important in the 2026 product names: **線状降水帯直前予測** and **線状降水帯発生** are separate notices.

### External sources (event time and evidence provenance)

- JMA official 2026 information categories:
  https://www.jma.go.jp/jma/kishou/books/hakusho/2026/index6.html
- Kawasaki City 2026-09-21 21:00 incident chronology, 12:58 alert:
  https://www.city.kawasaki.jp/601/page/0000190327.html
- FNN 12:58 eastern Kanagawa notice:
  https://www.fnn.jp/articles/-/1118379
- FNN 12:19 northern Izu notice:
  https://www.fnn.jp/articles/-/1118360
- Saitama 06:11 original notice:
  https://www.pref.saitama.lg.jp/bousai/mail/20260921_4.html
- Saitama 16:44 original notice:
  https://www.pref.saitama.lg.jp/bousai/mail/20260921_13.html
- Chiba original local bulletin on its emergency portal:
  https://www.bousai.pref.chiba.lg.jp/
- Forecast (20 Sep 22:59), FNN:
  https://www.fnn.jp/articles/-/1118173
- Weathernews 21 Sep 18:23: hourly Yokohama rain at 14:25:
  https://weathernews.jp/news/202609/210321/
- JMA incidence index (potentially stale; never use missing Sep item as proof of no event):
  https://www.data.jma.go.jp/senjo_list/list_senjoukousuitai.html

## Reproducible public F4 data observations

Publication commit: `133387e1a4648ed136a8d4904afb58219cd0cb90`.

### Purple F4-9C dashboard

Source: `web/data/research/f4_field_motion_research.geojson` at publication commit.

- Case ID/source slot: `20260921T130000Z` / **2026-09-21 22:00 JST**.
- Prospective as-of: **2026-09-21 22:15 JST** (`2026-09-21T13:15:00Z`).
- Target valid times: **22:30 and 22:45 JST**.
- 77 source components, 154 displayed convex-hull polygons (77 per lead).
- Source and forecast refer to a **selected fixed z8 radar mosaic**, not all Japan.
- The published projection-centroid bounding range is longitude **140.6619–145.2954 E**, latitude **36.8056–40.9669 N**. There are **0 projected centroids south of 36°N**, and **8 below 37°N**, so do not assert that *all Kanto* is categorically absent.
- `ARCHIVED`, `PENDING`, `research_only=true`, `risk_engine_allowed=false`, `lpz_forecast_generated=false`.
- These are **motion extrapolations of already observed >=30 mm/h component masks**, not LPZ formation/impact/official-issuance classifications.

No same-clock prediction for the 12:58 eastern Kanagawa imminence alert is contained in this single **22:15** purple public product. Comparing its locations with the 12:58 advisory is a time-mismatched comparison, **not an estimate of F4-9B Kanto forecast skill**.

### Fixed F4 geographic archive

Source: `web/data/research/f4_archived_geographic_research.geojson`; `source_run_id=35564667965`. This is a **different, archived descriptive/point extrapolation artifact**; it is NOT the 22:15 purple Lucas–Kanade forecast.

Count of OBSERVED_ORIGIN features at each frozen source slot (UTC converted to JST):

| 2026-09-21 JST | Observed source objects | Observed center range (latitude N) | Longitude E range |
| --- | ---: | --- | --- |
| 12:30 | 25 | 33.3236–36.5472 | 138.1613–140.3036 |
| 12:45 | 20 | 33.4154–35.1087 | 138.1229–140.3586 |
| 13:00 | 18 | 33.4796–35.5032 | 138.1064–140.0839 |
| 13:15 | 12 | 37.2937–38.5073 | 140.8090–141.9571 |
| 13:30 | 8 | 36.8203–38.4944 | 140.7431–142.4789 |
| 13:45 | 7 | 36.8774–38.5804 | 140.7211–141.8802 |
| 14:00 | 16 | 37.0574–38.5503 | 140.6277–141.9681 |

This archive DOES retain Kanto-area observed object centers near the **12:58** eastern Kanagawa imminence forecast (12:30/12:45/13:00 slots). The default archive page selects the **latest saved 14:00 slot**, at which its stored objects are clustered farther northeast. That selection does not mean Kanto rain was absent at 12:58.

## Findings and limitations

1. **Confirmed display/time mismatch**: the purple image visualizes an evening 22:15 as-of, while eastern Kanagawa imminence alert was issued 12:58 and observed heavy rain at Yokohama 14:25. An earlier source/target pair and the same geographic coverage are needed for model verification.
2. **Confirmed misreading risk**: a purple polygon is a transported >=30 mm/h *rain object*, not a JMA LPZ occurrence. JMA LPZ issuance requires different space-time accumulated rainfall, morphology and risk inputs.
3. **Confirmed source selection effect**: the separate frozen archive shows 12:30–13:00 centers in the south; its later 13:15–14:00 slots are farther north. Its 14:00 default gives a misleading impression if displayed as an explanation of the whole day.
4. **Not established**: exact z8 mosaic bounding coordinates for purple case; inspect only the frozen case manifest metadata locally. Not established: whether an official JMA Kanto occurrence alert was issued (as distinct from imminence forecast). Not established: Lucas–Kanade model skill in Kanto at 12:58/14:25; the displayed 22:15 sample cannot answer it.
5. **Do not change** the F4-9C source selection, prospective cohort, scores, GO/NO-GO rule, or JMA LPZ thresholds on the basis of this audit.

## Remaining verification

- **One metadata-only local check:** read `D:/program/lpz-risk-system_f4_9c_cohort/cases/20260921T130000Z.json` fields `source_slot_utc`, `prospective_as_of_utc`, `fixed_mosaic`, `discovery_parent`, `source_component_count`; compute z8 fixed-mosaic geographic box. Do not read `verifications/` or aggregate skill.
- Obtain the JMA occurrence-only original notice/official case entry for 2026-09-21 Kanto, or record **not verified**, without substituting imminence alerts.
- If archival data are available for exact contemporaneous Kanto slots, examine source acquisition and geographic coverage separately. Never retrospectively count an extrapolation as a real-time prospective forecast or mix F4 archival point extrapolation with F4-9C optical flow.

Outcome class at present: **TIME-AND-DISPLAY-CONTRACT MISMATCH CONFIRMED; KANTO LPZ OCCURRENCE AND F4-9B KANTO PERFORMANCE UNDETERMINED.**
