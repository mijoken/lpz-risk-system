# Phase 2I JAXA/GSMaP Access Hold — 2026-09-10

## Status

`BLOCKED_PROVIDER_AUTH_OR_IP_REVIEW_PENDING`

## Reason

The GSMaP Standard v8 FTP account is currently not reliable for production reconstruction. GitHub-hosted runners returned repeated `530 Login incorrect` responses and the user independently reproduced a password/login rejection with a local FFFTP client. The user has contacted the JAXA/EORC GSMaP office for clarification.

This state is therefore treated as an external provider authentication / access-control review, not as a rainfall-data scientific failure and not as proof of a missing GSMaP source file.

## Operational hold

Until JAXA/EORC replies:

- Do not launch automated GSMaP recovery attempts.
- Do not probe the FTP endpoint aggressively.
- Do not rerun the full three-provider Phase 2I workflow merely to retry GSMaP.
- Preserve GSMaP Gauge Standard v8 as the intended historical primary source once access is restored.
- IMERG Final V07 and NOAA CMORPH CDR reconstruction may continue independently.
- Two-provider IMERG/CMORPH source-disagreement analysis is allowed as descriptive research.
- Three-provider threshold calibration and threshold freezing remain blocked until GSMaP completeness is restored or a separately reviewed source-policy decision is made.

## Scientific guardrails

- Candidate threshold selected: `false`
- Hard-negative label creation: `false`
- Validation 2025 use: `false`
- Retrospective-test use: `false`
- Prospective-holdout use: `false`
- Risk engine allowed: `false`

## Existing partial Phase 2I state

The latest fail-closed reconstruction summary showed complete CMORPH Development episode representatives, partial IMERG representatives due transport failures, and partial GSMaP representatives due access failures. No incomplete provider is silently imputed or replaced.

## Resume condition

Resume GSMaP only after JAXA/EORC clarifies account/password/IP-access status and a minimal single-session authentication proof succeeds. Production access must remain conservative: one simultaneous FTP session maximum, sequential retrieval, and no aggressive probing.
