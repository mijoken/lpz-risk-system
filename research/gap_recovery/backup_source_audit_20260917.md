# Backup precipitation source audit — 2026-09-17

Status: research-only. No change to O8.1/O9/Primary/Risk Engine.

## Purpose
After Stage B-1 rejected feature-level constant-velocity extrapolation, evaluate independent or semi-independent observed precipitation products as gap-recovery inputs. A backup observation must retain explicit provenance and must never be relabeled as JMA HRPN observation/recovery.

## Current evidence

### JMA Analysis of Precipitation (R/A)
- Provider: JMA.
- Current JMA NWP outline describes R/A at 1 km spatial resolution, 10-minute update interval, representing 1-hour accumulated rainfall.
- Uses radar plus raingauge observations and is therefore scientifically close to the current JMA radar-derived Primary, but it is not provider-independent.
- Candidate role: high-priority same-provider backup / auxiliary observation. It cannot by itself solve a JMA-wide provider or delivery failure.

### NASA GPM IMERG Early Run
- Provider: NASA/PPS and GES DISC access paths.
- Official NASA product pages describe 30-minute temporal resolution, 0.1 degree / ~10 km spatial resolution, and ~4-hour Early Run latency.
- Candidate role: delayed independent-provider backup / retrospective gap repair and validation, not a direct 5-minute HRPN replacement.
- 2026 transition caveat: NASA's Aug. 6, 2026 update says Early/Late V08 switch is projected no sooner than winter 2026; until then Early/Late operate in hybrid mode. Preserve product/version metadata in any experiment.

### JAXA GSMaP
- Provider: JAXA.
- Existing project registration/access work exists, but machine-readable product/access/latency details must be re-verified from official JAXA documentation before an automated fusion experiment is frozen.
- Candidate role: independent-provider satellite precipitation backup, subject to access and latency verification.

## Scientific rules for Stage C
1. Never overwrite provenance. Proposed classes include OBSERVED_JMA, RECOVERED_JMA, OBSERVED_BACKUP_<SOURCE>, INTERPOLATED, MODEL_ESTIMATED, UNRESOLVED.
2. Do not compare raw grids as if resolution/cadence/accumulation semantics were identical. Normalize time support and spatial support first.
3. Primary evaluation is system meaning: rain-area/core location, intensity band, morphology/linearity, motion/persistence, and threshold-flip behavior. Scalar bias/MAE/correlation are secondary diagnostics.
4. Backup data arriving later may upgrade an earlier estimate, but the original estimate and its error should remain available for learning/audit.
5. Risk Engine remains locked.

## Stage C entry decision
Start with NASA IMERG Early because official machine-readable access, cadence, spatial resolution, and latency are currently documented and independently verifiable. In parallel, re-verify JAXA GSMaP machine-readable access. JMA R/A remains scientifically attractive but correlated in provider/failure domain.
