# Phase 2B ERA5 Historical Environment — Available-Window Baseline

Date: 2026-09-10 JST

## Status

The authenticated ERA5 historical-environment pipeline has been validated end-to-end for all source times currently published by CDS.

- Frozen JMA realized-positive anchors: 851
- Requested snapshot mappings: 5,106
- Frozen ERA5 date × primary-subdivision requests: 104
- Validated ERA5 request descriptors available now: 102
- Snapshot feature rows available now: 4,962
- Pending recent snapshots due only to ERA5 publication latency: 144
- Hard-missing request indices: none
- Hard-missing snapshots: 0
- Future ERA5 source-time use: 0
- Available-window completeness: PASS
- Full reconstruction completeness: PENDING RECENT SOURCE AVAILABILITY
- Risk engine: OFF

## Recent source-availability tail

Two frozen requests are not yet available from CDS:

- request 102: 2026-09-08 / primary subdivision code 210010 / source hours 04:00–10:00 UTC
- request 103: 2026-09-08 / primary subdivision code 230010 / source hours 04:00–09:00 UTC

CDS reported during Run 34361612066 that the latest ERA5 pressure-level source time then available was `2026-09-04 14:00` UTC. These two requests are therefore classified as `PENDING_SOURCE_AVAILABILITY`, not as data loss or model failure.

No interpolation, future-time substitution, GFS substitution, or imputation is permitted for this tail merely to make the table complete. The same frozen request definitions will be replayed after CDS publishes the requested source times.

## Scientific payload preserved per available snapshot

Each available snapshot row retains:

- anchor_id
- primary subdivision code
- snapshot offset (T-180, T-120, T-90, T-60, T-30, T0)
- requested snapshot time
- floor-hour ERA5 source time and lag minutes
- RH500 mean
- RH700 mean
- fraction satisfying RH500 > 60% and RH700 > 60%
- 600 hPa wind speed and direction
- 850 hPa wind speed and direction
- q at 1000, 925, and 850 hPa
- exactness = `PROXY_REANALYSIS`
- risk_score = null

## Guardrails frozen by this baseline

1. Multiple ERA5 valid times within one CDS request are first-class keys and must never overwrite each other.
2. Snapshot time alignment uses the latest whole ERA5 hour less than or equal to the requested snapshot time; future-time use is forbidden.
3. Recent ERA5 publication latency is represented explicitly as `PENDING_SOURCE_AVAILABILITY`.
4. True missing historical data must still fail the available-window gate.
5. ERA5 is a reanalysis proxy for the historical environmental field; it is not relabeled as exact reproduction of the live GFS pipeline.
6. The Risk Engine remains disabled.

## Evidence runs

- Full historical reconstruction source run: GitHub Actions Run 34361612066
- Source-availability-aware finalize run: GitHub Actions Run 34370550473
- Finalized result: 102/104 request descriptors, 4,962/5,106 snapshot rows, 144 recent pending snapshots, hard missing = 0, future source time = 0.

## Next phase

Build the Historical Rainfall / Hard Negative Candidate pipeline. The JMA official catalogue confirms that analyzed precipitation is a 1 km, 1-hour precipitation GRIB2 product; historical `解析雨量データ` from 2017 onward is provided annually through viewing / JMBSC media rather than being assumed to be an unrestricted public bulk API. Until an actual historical payload is obtained, candidate-generation logic may be implemented and tested synthetically, but no real Hard Negative label may be emitted.
