# Phase 2L-B — Literature-Guided LPZ Mechanism & Discriminant Evidence Baseline

Date: 2026-09-10 JST

## Status

`PASS_LITERATURE_GUIDED_MECHANISM_BASELINE`

This phase freezes externally supported physical hypotheses before Heavy-Rain Negative construction. It does **not** tune a classifier, select a new empirical threshold, inspect Validation 2025, inspect the 2026 retrospective test, inspect the prospective holdout, fuse rainfall providers, infer unavailable convergence fields, or enable the risk engine.

## Research question

> Among heavy-rain episodes with comparable rainfall severity, what distinguishes cases that organize into quasi-stationary linear precipitation systems (senjo-kousuitai / LPZ) from cases that do not?

The objective is not to rediscover the literature blindly. Existing mechanism evidence is used to define a priori variables and contrasts, after which the frozen 2023-2024 Development population is used for independent reproduction, falsification, refinement, and possible discovery of discriminants that reduce false alarms beyond the established favorable-condition framework.

## Core external evidence

### 1. Kato (2020): six favorable conditions are sensitivity-oriented, not sufficient conditions

Reference: Teruyuki Kato, Journal of the Meteorological Society of Japan, 98(3), 485-509, DOI 10.2151/jmsj.2020-029.

The six statistically constructed favorable conditions are:

1. 500-m-height water-vapor flux (FLWV) > 150 g m^-2 s^-1;
2. distance from 500 m to LFC (dLFC) < 1000 m;
3. RH500 > 60% and RH700 > 60%;
4. SREH > 100 m^2 s^-2;
5. synoptic-scale ascent at 700 hPa (400-km mean W700 > 0 in the paper's sign convention);
6. equilibrium level EL > 3000 m.

Critical interpretation: the thresholds were set so as not to miss prior events and therefore can produce false alarms. Kato explicitly states that additional conditions are needed to reduce false alarms, giving high equivalent potential temperature and low-level wind convergence as examples.

This creates a direct research target for LPZ-Risk-System:

> Do rainfall-matched non-LPZ heavy-rain events also satisfy much of the six-condition envelope, and if so, which additional dynamical, organizational, persistence, geographic, or trajectory variables separate them from LPZ positives?

### 2. Goto & Satoh (2022): low-level water-vapor flux and vertical shear; wind speed may dominate flux anomaly

Reference: SOLA 18A (2022), DOI 10.2151/sola.18A-003.

A 20-year satellite/reanalysis statistical study identifies low-level water-vapor flux and vertical wind shear as essential environmental factors. For Baiu-season Kyushu cases, the circulation pattern strengthens the pressure gradient and low-level winds; enhanced water-vapor flux is attributed more to stronger winds than to anomalous water-vapor content alone.

Implication: simple low-level specific humidity q is not an adequate substitute for moisture transport. The existing Phase 2K result that BBox-mean q has weak marginal association with rainfall must not be interpreted as low-level moisture-transport irrelevance.

### 3. Sato/Hosotani line of evidence and 2023 Kyushu analysis: decompose water-vapor flux and SREH

Reference: SOLA 19A (2023), "Characteristics Analysis of the Senjo-Kousuitai Conditions in the Kyushu Region in Early July".

The study examines FLWV and SREH over about 20 years and reports that anomalous wind speed contributes more than humidity to anomalous water-vapor flux. Lower-layer zonal vertical shear and meridional flow contribute materially to SREH.

Implication: later testing should retain moisture amount, wind speed, vector transport, and vertical-shear/helicity structure as separate coordinates instead of collapsing them into one generic "humid" feature.

### 4. Naka & Takemi (2023): deep moist absolutely unstable layers and low-level moisture-flux convergence

Reference: SOLA 19A (2023), "Characteristics of the Environmental Conditions for the Occurrence of Recent Extreme Rainfall Events in Northern Kyushu, Japan".

The studied extreme-rain cases were not necessarily characterized by exceptionally large conventional instability; rather, the troposphere was nearly saturated, deep moist absolutely unstable layers (MAULs) existed, and large lower-tropospheric moisture-flux convergence was observed. Deep MAUL volume correlated positively with area-total rainfall, and humid/MAUL structure appeared before the heavy rainfall.

Implication: CAPE-only discrimination is unlikely to be sufficient. Vertical thermodynamic structure and the persistence/formation of saturated or moist-absolutely-unstable layers are literature-supported candidate discriminants.

### 5. July 2020 Kyushu case studies: convergence line/zone + strong moisture inflow + mesoscale depressions

Reference: SOLA 17 (2021), "Characteristics of Atmospheric Environments of Quasi-Stationary Convective Bands in Kyushu, Japan during the July 2020 Heavy Rainfall Event".

QSCBs were located along low-level convergence lines/zones with extremely large water-vapor flux on their inflow side. Mesoscale Baiu frontal depressions enhanced horizontal winds and thereby low-level moisture flux.

Implication: the spatial relationship between inflow, convergence zone, and rainband is more physically specific than a domain-average humidity threshold.

### 6. Persistence matters, not only instantaneous magnitude

Reference: SOLA 17B (2021), "Moisture Supply, Jet, and Silk-Road Wave Train Associated with the Prolonged Heavy Rainfall in Kyushu, Japan in Early July 2020".

The event featured extreme multi-day moisture-flux convergence, but instantaneous moisture flux itself was not uniquely extreme relative to other subtropical-jet/Baiu environments. A distinguishing feature was the persistence of the moisture-flux maximum anchored around Kyushu.

Implication: a time-integrated or persistence coordinate may discriminate better than a single T0 value. The Phase 2K six-time trajectory should therefore be expanded to physically defined transport/convergence variables when scientifically available.

### 7. 600-hPa flow structure is independently supported

Reference: SOLA 21A (2025), "A Statistical Study on Senjo-Kousuitai in a Regional Reanalysis for Japan (RRJ-Conv)".

Using 5-km hourly regional reanalysis from 1976-2020 and 6760 objectively extracted events, the strongest relation for SK orientation was with 600-hPa wind direction, with a small clockwise offset. Environmental winds exhibited veering, and the veering magnitude decreased after onset.

Implication: the current Phase 2K 600-hPa wind and 850/600 direction-difference descriptors may contain genuine organizational information, but the present 850/600 angular difference is not a substitute for full vector shear, storm-relative flow, or convergence.

### 8. Hierarchical organization and deep inflow

Reference: JMSJ 101(4) (2023), "A Hierarchical Structure of the Heavy Rainfall Event over Kyushu in July 2020".

The study describes organized precipitation systems embedded within larger mesoscale organization, with deep inflow layers and MAULs. This supports treating LPZ formation as a hierarchy: favorable large-scale environment -> mesoscale organization -> repeated convective regeneration -> quasi-stationary rainfall band.

Implication: environmental favorability and actual organization should be represented as different evidence layers.

## Current JMA direction and open space

JMA operational/research material in 2025-2026 emphasizes that senjo-kousuitai formation modes are highly diverse and that a formation-mode classification table is being used to reduce false alarms. JMA also continues to emphasize lower-tropospheric water-vapor flow/amount, convergence, upper-level flow/cold air, and three-dimensional moisture observations.

This means the system should **not** assume one nationally universal deterministic mechanism. A stronger target is:

1. reproduce the broad favorable-condition envelope;
2. stratify by formation mode / synoptic regime / geography where possible;
3. identify variables that reduce false positives among rainfall-matched heavy-rain events;
4. test whether those additions generalize across providers and later across untouched Validation.

## Literature-to-system variable map

| Mechanism / variable | Literature status | Current system status | Required action |
|---|---|---|---|
| RH500 / RH700 | established favorable condition | AVAILABLE | retain; do not double-count redundant humidity composites |
| 500-m FLWV | core favorable condition | NOT EXACTLY AVAILABLE | implement physically faithful near-500-m interpolation / transport |
| dLFC | core favorable condition | NOT AVAILABLE | add thermodynamic profile and exact LFC calculation |
| SREH | core favorable condition | NOT AVAILABLE | implement exact storm-motion + helicity calculation |
| 700-hPa large-scale ascent | core favorable condition | PENDING | retrieve/convert vertical velocity and freeze sign/area semantics |
| EL | core favorable condition | NOT AVAILABLE | add full thermodynamic profile and exact EL calculation |
| low-level wind convergence | explicit false-alarm-reduction candidate in Kato | NOT AVAILABLE | add horizontal derivatives; do not infer from 850/600 angles |
| moisture-flux convergence | supported in multiple studies | NOT AVAILABLE | add full vector moisture transport + horizontal divergence |
| 850/600 winds | organizational support | AVAILABLE AS DESCRIPTORS | retain, but add true vector shear later |
| 600-hPa direction / rainband orientation | supported statistically | PARTIALLY AVAILABLE | test orientation mismatch once rainband geometry exists |
| persistence of moisture transport/convergence | supported | NOT AVAILABLE AS EXACT FEATURE | add multi-time persistence/integral coordinates |
| MAUL depth/volume | supported for extreme-rain environments | NOT AVAILABLE | add vertical thermodynamic structure |
| CAPE | not sufficient alone in cited extreme-rain studies | NOT AVAILABLE | may compute later as contextual variable, not privileged discriminator |
| terrain/orographic triggering | physically/case supported | NOT YET SYSTEMATIC | add terrain-relative inflow/orographic-lift context |
| formation mode / synoptic regime | JMA says highly diverse | NOT CLASSIFIED | build descriptive regime labels before universal thresholding |

## A priori hypotheses frozen for Development comparison

These are hypotheses to test, not findings of this project:

### H1 — Transport exceeds moisture amount
At matched rainfall severity, LPZ positives will show stronger and/or more persistent low-level moisture **transport** than heavy-rain negatives even when simple low-level q overlaps substantially.

### H2 — Convergence/organization reduces Kato-style false alarms
Among events occupying a similarly favorable moisture/instability envelope, explicit low-level wind convergence or moisture-flux convergence will improve separation between LPZ and non-LPZ heavy rain.

### H3 — Persistence matters
Time persistence of transport/convergence and repeated maintenance of a favorable upstream inflow will discriminate more strongly than instantaneous T0 extremes alone.

### H4 — Vertical wind structure matters independently of moisture
True vertical shear/SREH and 600-hPa flow orientation will add information beyond humidity and rainfall severity.

### H5 — Deep saturated/MAUL structure can distinguish organized sustained convection
Vertical thermodynamic structure, especially deep near-saturation/MAUL metrics, will provide information not captured by RH500/RH700 alone.

### H6 — There is no single nationally universal separator
Effect sizes and useful discriminants will vary by geography, season, formation mode, and synoptic regime. Pooled-national statistics must therefore be accompanied by stratified analysis.

### H7 — Rainband-relative geometry may matter more than domain means
Upstream sampling, convergence-line-relative sampling, rainband orientation mismatch, and terrain-relative inflow will outperform coarse retrieval-BBox means for some mechanisms.

## What would count as a useful new discovery

The project should not claim novelty merely by re-finding high humidity or high FLWV. Higher-value findings would include:

- a reproducible variable that materially separates rainfall-matched false-alarm-like negatives from positives **after** controlling for the six favorable conditions;
- a persistence or trajectory statistic that improves discrimination beyond T0 state;
- a formation-mode-specific discriminator that explains why a pooled threshold fails;
- an interaction (for example transport x convergence x orientation) that is robust across IMERG, CMORPH, and confirmatory GSMaP;
- an explicit condition under which an established criterion stops being informative;
- a reproducible geographic/terrain dependency that explains regional threshold differences;
- a source-disagreement/confidence pattern that predicts when rainfall-based classification is unreliable.

## Phase 2K cross-check

Existing Development Positive-only results already show partial independent consistency with the literature:

- realized positives commonly occupy a moist mid-level state;
- T0 RH-related descriptors are the strongest source-robust rainfall associations in the current limited descriptor set;
- simple low-level q is weak as a marginal correlate, which is compatible with literature emphasizing flux (q x wind) rather than q alone;
- 600-hPa flow has a weaker but source-consistent relationship and is independently supported as organizationally relevant;
- the current system cannot yet test the strongest literature-guided discriminants: exact FLWV, convergence, moisture-flux convergence, dLFC, SREH, EL, MAUL, and true vector shear.

No retrospective relabeling of Phase 2K is permitted. These are cross-study consistency observations only.

## Experimental consequence for the next phase

Phase 2L-C should construct a **Development-only spatial heavy-rain comparison population** without using the environmental hypotheses to select cases. Case selection must remain rainfall-based and source-native to avoid selecting negatives by the very atmospheric variables later being tested.

After rainfall-matched candidate construction, environmental variables are evaluated in two tiers:

1. **Tier A — currently available descriptors:** RH500, RH700, joint-moist fraction, q1000/q925/q850, 850/600 winds and trajectories;
2. **Tier B — literature-required exact mechanisms:** FLWV, low-level convergence, moisture-flux convergence, dLFC, SREH, W700, EL, MAUL/thermodynamic-profile features, true vector shear, persistence/integrals, terrain-relative inflow, and rainband-relative orientation.

This ordering protects against circular candidate selection.

## Statistical safeguards

- Match or stratify by rainfall severity before calling a variable an LPZ discriminator.
- Control season and geography; do not interpret pooled climatological differences as mechanism.
- Treat repeated LPZ regions/dates as clustered observations, not independent rows.
- Preserve provider-native rainfall; do not average IMERG/CMORPH/GSMaP into synthetic truth.
- Use episode-aware uncertainty / bootstrap or equivalent cluster-aware intervals.
- Evaluate incremental information conditional on established coordinates; marginal correlation alone is insufficient.
- Avoid feature multiplicity and redundant double-counting.
- Freeze all Development-derived transformations before touching Validation 2025.

## Guardrails

- New empirical threshold selected: `false`
- Heavy-rain candidate generated in this literature phase: `false`
- Hard-negative label: `null`
- Validation 2025 used: `false`
- Retrospective 2026 used: `false`
- Prospective holdout used: `false`
- Rainfall source fusion used: `false`
- GSMaP used for discovery: `false`
- Unavailable convergence inferred: `false`
- Risk score: `null`
- Risk engine allowed: `false`

## Next gate

`PHASE_2L_C_SPATIAL_RAINFALL_MATCHED_CANDIDATE_POPULATION`

The next phase should identify non-LPZ heavy-rain candidates using rainfall and spatial/temporal rain geometry only, then compare them against positives under the pre-frozen literature-guided hypotheses above. The highest-priority model-data engineering extension after candidate construction is exact low-level moisture transport and convergence, because the literature repeatedly points to those as both mechanistically important and potentially useful for reducing false alarms.
