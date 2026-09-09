# Phase 2I Provider Access Guardrail Baseline — 2026-09-10

## Purpose

Freeze provider-side access safety before continuing full DEVELOPMENT rainfall reconstruction. This document does not change scientific labels, thresholds, or risk logic.

## NASA GES DISC / IMERG Final V07

Official Earthdata/GES DISC guidance indicates:

- Granules may be downloaded in parallel, but concurrent connections should be limited to no more than 3 in the general GES DISC FAQ.
- A February 2026 GES DISC response specific to IMERG asked users to limit concurrent downloads to no more than 2.
- CMR Search rate limiting returns HTTP 429 and a Retry-After header; clients should honor Retry-After and reduce concurrency.
- Service temporarily unavailable / concurrent connection limit errors can occur under excessive concurrency or server load.

LPZ-RISK therefore adopts a stricter operational policy:

- max parallel IMERG jobs: 1
- max download threads within that job: 2
- max effective download concurrency: 2
- transport retries are bounded
- HTTP 429 must be classified as rate limiting and Retry-After must be honored when exposed
- empty granule results or decoded-field incompleteness are not hidden by transport retry

Observed `Errno 101: Network is unreachable` failures happened before a usable HTTP response was received. This is classified as a transport-route failure, not positive evidence of NASA rate limiting. Exact network-segment root cause cannot be proven without provider/runner network logs.

## JAXA/EORC GSMaP FTP

Official JAXA GSMaP FAQ states:

- If correct credentials cannot access the FTP service and there is no maintenance announcement, the user's IP address may have been blocked for some reason.
- Users should use an FTP client such as FileZilla or WinSCP; major web browsers do not support FTP access.
- Slow FTP may be caused by temporary network congestion or server trouble; persistent problems should be reported to JAXA.

No public numeric threshold for session count, logins per minute, or transfer rate was found in the official GSMaP FAQ/guide.

LPZ-RISK therefore adopts a conservative policy:

- max simultaneous GSMaP FTP sessions: 1
- no aggressive probing
- bounded retry only
- target architecture: one long-lived FTP login followed by sequential retrievals, rather than repeated short login sessions
- `530 Login incorrect` with known-good credentials is NOT treated as proof of a bad password; it is classified as unresolved auth/IP-block/provider-session-control until isolated
- `550` is treated separately as path/file absence

## Manual diagnostic

A single low-impact manual FTP test from the user's normal Windows network is scientifically and operationally useful:

1. Use WinSCP or FileZilla.
2. Host: `hokusai.eorc.jaxa.jp`.
3. Use the registered GSMaP credentials.
4. Browse to `/standard/v8/hourly_G`.
5. Optionally browse one known historical date directory and download only one hourly Gauge v8 file.
6. Do not bulk-download during the diagnostic.

Interpretation:

- Manual login succeeds while GitHub-hosted runner intermittently returns 530: strong evidence for runner-IP/session-control interaction rather than account credential failure.
- Manual login also returns 530: contact JAXA/EORC with public IP, organization, access date/time, as their FAQ instructs.
- Login succeeds but one date/file is absent: investigate provider file/path availability separately; do not classify as an access block.

## Fallback

JAXA G-Portal distributes the same GSMaP_MVK/Gauge scientific product family in HDF format and requires free user registration for downloads. It is retained as an optional fallback, not a core dependency. G-Portal is undergoing a system renewal around October 2026, including SFTP endpoint/authentication changes, so migration should not be performed casually during the transition.

## Scientific guardrails unchanged

- DEVELOPMENT only
- no Validation 2025 use
- no Retrospective Test use
- no Prospective Holdout use
- no candidate threshold selection
- no hard-negative label creation
- Risk Engine remains OFF
