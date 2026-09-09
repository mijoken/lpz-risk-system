# Phase 2B ERA5 Payload + Batch Reconstruction Pilot Baseline — 2026-09-09

## Status

**PASS — authenticated ERA5 payload retrieval and checkpointed multi-request reconstruction proven.**

## Authenticated payload proof

Workflow run `34359022859` completed successfully after CDS dataset licence acceptance and correction of an overly strict relative-humidity guardrail.

Proven gates:

- GitHub `CDSAPI_KEY` secret present and masked: PASS
- CDS authentication: PASS
- ERA5 pressure-level licence: ACCEPTED
- non-empty GRIB payload download: PASS
- ecCodes decode: PASS
- required field presence: 9 / 9
- required field finite-value validation: PASS
- source semantics retained as `ERA5 / PROXY_REANALYSIS`
- Risk Engine: OFF

Proof request:

- date: `2023-06-01`
- primary subdivision code: `390030`
- UTC times: `20:00, 21:00, 22:00, 23:00`
- downloaded bytes: `21,120`
- grid points per required field: `56`

Required scientific fields validated:

- RH 500 hPa
- RH 700 hPa
- U/V 600 hPa
- U/V 850 hPa
- specific humidity 1000 hPa
- specific humidity 925 hPa
- specific humidity 850 hPa

## ERA5 RH guardrail correction

The first decoded payload revealed RH values slightly above 100% at 500/700 hPa. The previous `<=101%` transport gate was scientifically incorrect for ERA5 pressure-level RH, which is defined with respect to mixed phase and can legitimately be supersaturated.

The decoder now:

- does not clip ERA5 RH at 100%;
- records supersaturated point counts;
- uses only a broad transport-sanity range for corruption detection;
- keeps Kato-style `RH > 60%` diagnostics unchanged.

Proof payload supersaturation evidence:

- RH supersaturated points across required 500/700 hPa fields: `57 / 112`
- RH500 max: about `106.72%`
- RH700 max: about `106.86%`

## Three-request checkpointed batch pilot

Workflow run `34359558559` proved restart-safe multi-request reconstruction.

Result:

- selected requests: `3`
- successes: `3`
- failures: `0`
- batch gate: `PASS`
- full manifest request count: `104`

Pilot requests:

1. `0000_2023-06-01_390030` — 21,120 bytes — SUCCESS
2. `0001_2023-06-02_220040` — 24,720 bytes — SUCCESS
3. `0002_2023-06-02_230020` — 29,664 bytes — SUCCESS

For each request the pipeline performs:

`download GRIB -> scientific decode -> compact JSON descriptor -> checkpoint update -> delete temporary GRIB`

Therefore the repository does not accumulate raw ERA5 binaries.

## Frozen operational policy

Before expanding to all 104 requests:

- keep request unit `UTC date × JMA primary subdivision`;
- preserve no-future-time floor-hour alignment;
- keep source/exactness tags on every row;
- persist checkpoints and compact descriptors only;
- never infer LPZ labels from ERA5 environmental fields;
- do not enable Risk Engine.

## Current gates

```text
ERA5 authenticated access                 PASS
ERA5 dataset licence                      PASS
ERA5 one-request payload                  PASS
ERA5 scientific decode                    PASS
ERA5 three-request batch pilot             PASS
104-request historical reconstruction      READY_NOT_YET_EXECUTED
historical rainfall payload                NOT YET ACQUIRED
hard-negative registry                     NOT BUILT
risk engine                                OFF
```
