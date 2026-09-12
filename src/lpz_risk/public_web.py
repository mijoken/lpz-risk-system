"""Build and validate the public GitHub Pages JSON products.

The public layer never decides whether the scientific model is released.  It
reads the frozen K2 state and converts an already-produced Phase 2L-L source
health report into browser-facing products.  While K2 is locked every regional
risk value is forced to null.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]

SYSTEM_SCHEMA = ROOT / "web" / "schema" / "public_system_status.schema.json"
SOURCE_SCHEMA = ROOT / "web" / "schema" / "public_source_health.schema.json"
LATEST_SCHEMA = ROOT / "web" / "schema" / "public_latest.schema.json"

GEOGRAPHY_PUBLIC_PATH = "assets/japan_primary_subdivisions.geojson"
LATEST_PUBLIC_PATH = "data/latest.json"
SOURCE_HEALTH_PUBLIC_PATH = "data/source_health.json"
DATA_CONTRACT_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0.0"

EXPECTED_K2_GATE = "PASS_PHASE2L_K2_V07_BOUNDARY_AND_V08_DEFERRED_VALIDATION_FREEZE"
EXPECTED_VALIDATION = "DEFERRED_PENDING_IMERG_FINAL_V08"
PRIMARY_ID = "H_PRIMARY_Q850_T0H"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _git_head(root: Path = ROOT) -> str | None:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    value = cp.stdout.strip()
    return value if cp.returncode == 0 and value else None


def verify_k2_lock(k2: dict[str, Any]) -> dict[str, Any]:
    if k2.get("gate") != EXPECTED_K2_GATE:
        raise RuntimeError(f"unexpected K2 gate: {k2.get('gate')!r}")

    state = k2.get("validation_state")
    if not isinstance(state, dict):
        raise RuntimeError("K2 validation_state missing")
    if state.get("status") != EXPECTED_VALIDATION:
        raise RuntimeError(f"unexpected validation state: {state.get('status')!r}")
    if state.get("primary_confirmatory_test_run") is not False:
        raise RuntimeError("Primary confirmatory test state is not frozen false")
    if state.get("primary_outcome_opened") is not False:
        raise RuntimeError("Primary outcome seal is not intact")
    if state.get("2025_era5_environment_outcomes_may_be_opened_now") is not False:
        raise RuntimeError("K2 unexpectedly permits opening 2025 ERA5")
    if state.get("risk_engine_allowed") is not False:
        raise RuntimeError("K2 unexpectedly permits the risk engine")

    primary = (
        k2.get("upstream_protocol", {})
        .get("primary_hypothesis", {})
        .get("id")
    )
    if primary != PRIMARY_ID:
        raise RuntimeError(f"unexpected frozen Primary id: {primary!r}")
    return state


def verify_phase_l_seal(phase_l: dict[str, Any]) -> None:
    summary = phase_l.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError("Phase 2L-L report summary missing")
    if summary.get("research_validation_status") != EXPECTED_VALIDATION:
        raise RuntimeError("Phase 2L-L validation state does not match K2")
    if summary.get("2025_era5_environment_opened") is not False:
        raise RuntimeError("Phase 2L-L says 2025 ERA5 environment was opened")
    if summary.get("primary_confirmatory_test_run") is not False:
        raise RuntimeError("Phase 2L-L says the Primary confirmatory test ran")
    if summary.get("risk_engine_allowed") is not False:
        raise RuntimeError("Phase 2L-L unexpectedly allows the risk engine")


def _public_role(role: Any) -> str:
    value = str(role or "")
    if value in {"LIVE_MANDATORY", "LIVE_SUPPLEMENTARY", "RESEARCH_ONLY"}:
        return value
    return "RESEARCH_ONLY"


def _freshness_for_row(row: dict[str, Any]) -> str:
    health = str(row.get("health") or "UNKNOWN")
    role = _public_role(row.get("role"))
    if role == "RESEARCH_ONLY":
        return "NOT_APPLICABLE"
    if health == "PASS":
        return "FRESH"
    if health == "STALE":
        return "STALE"
    if health == "FAIL" and not row.get("data_time"):
        return "MISSING"
    if health == "PENDING":
        return "NOT_APPLICABLE"
    return "UNKNOWN"


def _source_message(row: dict[str, Any]) -> str | None:
    reason = row.get("reason")
    error = row.get("error")
    if error:
        return f"{reason or 'SOURCE_ERROR'}: {error}"
    return str(reason) if reason else None


def build_source_health(
    phase_l: dict[str, Any], *, generated_at_utc: str
) -> dict[str, Any]:
    rows = phase_l.get("live_source_health")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Phase 2L-L report has no live_source_health rows")

    sources: list[dict[str, Any]] = []
    mandatory_health: list[str] = []

    for row in rows:
        if not isinstance(row, dict):
            raise RuntimeError("invalid Phase 2L-L live source row")
        role = _public_role(row.get("role"))
        health = str(row.get("health") or "UNKNOWN")
        if health not in {"PASS", "STALE", "DEGRADED", "FAIL", "PENDING", "UNKNOWN"}:
            health = "UNKNOWN"
        if role == "LIVE_MANDATORY":
            mandatory_health.append(health)

        age = row.get("data_age_seconds")
        limit = row.get("freshness_limit_seconds")
        sources.append(
            {
                "source_id": str(row.get("source_id") or ""),
                "name": str(row.get("source_name") or row.get("source_id") or "Unknown source"),
                "role": role,
                "health": health,
                "probe_status": None if row.get("probe_status") is None else str(row.get("probe_status")),
                "data_time_utc": row.get("data_time"),
                "age_seconds": None if age is None else max(0, int(age)),
                "freshness_limit_seconds": None if limit is None else max(0, int(limit)),
                "freshness": _freshness_for_row(row),
                "message": _source_message(row),
            }
        )

    earth = phase_l.get("earthdata_imerg_research_source")
    if isinstance(earth, dict):
        v8_available = bool(earth.get("v8_available"))
        auth = str(earth.get("authentication") or "UNKNOWN")
        if auth == "FAIL":
            health = "DEGRADED"
        elif v8_available:
            health = "PASS"
        elif earth.get("imerg_final_v08_metadata") == "EXPECTED_PENDING":
            health = "PENDING"
        else:
            health = "UNKNOWN"
        sources.append(
            {
                "source_id": "nasa_earthdata_imerg",
                "name": "NASA GPM IMERG Final",
                "role": "RESEARCH_ONLY",
                "health": health,
                "probe_status": str(earth.get("imerg_final_v08_metadata") or "UNKNOWN"),
                "data_time_utc": None,
                "age_seconds": None,
                "freshness_limit_seconds": None,
                "freshness": "NOT_APPLICABLE",
                "message": (
                    "Final V08 retrospective coverage is available; validation re-entry is manual."
                    if v8_available
                    else "Final V08 retrospective coverage remains pending."
                ),
            }
        )

    if mandatory_health and all(x == "PASS" for x in mandatory_health):
        overall = "PASS"
    elif any(x == "FAIL" for x in mandatory_health):
        overall = "FAIL"
    else:
        overall = "DEGRADED"

    return {
        "schema_version": SCHEMA_VERSION,
        "product": "LPZ_PUBLIC_SOURCE_HEALTH",
        "generated_at_utc": generated_at_utc,
        "overall_status": overall,
        "sources": sources,
    }


def _release_object(k2_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": "LOCKED_VALIDATION_PENDING",
        "risk_engine_allowed": False,
        "validation_status": str(k2_state["status"]),
        "model_version": None,
        "message": "Risk output remains locked until the frozen 2025 confirmatory validation is resolved.",
    }


def _feature_metadata(feature: dict[str, Any]) -> tuple[str, str]:
    props = feature.get("properties") or {}
    code = str(props.get("region_code") or feature.get("id") or "")
    name = str(props.get("name_ja") or "")
    if len(code) != 6 or not code.isdigit():
        raise RuntimeError(f"invalid public geometry region code: {code!r}")
    if not name:
        raise RuntimeError(f"public geometry region name missing: {code}")
    return code, name


def build_latest(
    geography: dict[str, Any],
    k2_state: dict[str, Any],
    *,
    generated_at_utc: str,
) -> dict[str, Any]:
    if geography.get("type") != "FeatureCollection":
        raise RuntimeError("public geography is not a FeatureCollection")
    features = geography.get("features")
    if not isinstance(features, list) or not features:
        raise RuntimeError("public geography has no features")

    seen: set[str] = set()
    regions: list[dict[str, Any]] = []
    for feature in features:
        if not isinstance(feature, dict):
            raise RuntimeError("invalid geography feature")
        code, name = _feature_metadata(feature)
        if code in seen:
            raise RuntimeError(f"duplicate geography region code: {code}")
        seen.add(code)
        regions.append(
            {
                "region_code": code,
                "name_ja": name,
                "prefecture_name_ja": None,
                "geometry_key": code,
                "data_time_utc": None,
                "freshness": "UNKNOWN",
                "display_state": "NO_PUBLIC_RISK",
                "observed": None,
                "risk": None,
            }
        )

    regions.sort(key=lambda row: row["region_code"])
    return {
        "schema_version": SCHEMA_VERSION,
        "product": "LPZ_PUBLIC_LATEST",
        "generated_at_utc": generated_at_utc,
        "release": _release_object(k2_state),
        "map": {
            "geographic_unit": "JMA_PRIMARY_SUBDIVISION",
            "geometry_path": GEOGRAPHY_PUBLIC_PATH,
            "region_count": len(regions),
        },
        "regions": regions,
    }


def build_system_status(
    source_health: dict[str, Any],
    k2_state: dict[str, Any],
    *,
    generated_at_utc: str,
    pipeline_state: str,
    run_id: str | None,
    commit_sha: str | None,
) -> dict[str, Any]:
    if pipeline_state not in {"PASS", "DEGRADED", "FAIL", "UNKNOWN"}:
        raise ValueError(f"invalid pipeline_state: {pipeline_state}")

    source_status = source_health["overall_status"]
    if pipeline_state == "FAIL" or source_status == "FAIL":
        overall = "OFFLINE"
    elif pipeline_state in {"DEGRADED", "UNKNOWN"} or source_status == "DEGRADED":
        overall = "DEGRADED"
    else:
        overall = "ONLINE"

    release = _release_object(k2_state)
    return {
        "schema_version": SCHEMA_VERSION,
        "product": "LPZ_PUBLIC_SYSTEM_STATUS",
        "generated_at_utc": generated_at_utc,
        "overall_operational_status": overall,
        "scientific_release": {
            "state": release["state"],
            "risk_engine_allowed": False,
            "primary_confirmatory_test_run": False,
            "validation_status": release["validation_status"],
            "primary_hypothesis_id": PRIMARY_ID,
            "imerg_final_version": None,
            "reason": release["message"],
        },
        "pipeline": {
            "state": pipeline_state,
            "last_success_at_utc": generated_at_utc if pipeline_state == "PASS" else None,
            "run_id": run_id,
            "commit_sha": commit_sha,
            "message": "Public JSON products built and validated before publication.",
        },
        "public_data": {
            "latest_path": LATEST_PUBLIC_PATH,
            "source_health_path": SOURCE_HEALTH_PUBLIC_PATH,
            "geography_path": GEOGRAPHY_PUBLIC_PATH,
            "data_contract_version": DATA_CONTRACT_VERSION,
        },
        "notices": [
            "Research/monitoring system under validation; not an official warning service.",
            "Risk output is locked pending the frozen 2025 confirmatory validation.",
        ],
    }


def _schema_errors(instance: dict[str, Any], schema_path: Path) -> list[str]:
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
    out: list[str] = []
    for error in errors:
        location = ".".join(str(x) for x in error.absolute_path) or "<root>"
        out.append(f"{schema_path.name}:{location}: {error.message}")
    return out


def validate_products(
    *,
    system_status: dict[str, Any],
    source_health: dict[str, Any],
    latest: dict[str, Any],
    geography: dict[str, Any],
) -> None:
    errors: list[str] = []
    errors += _schema_errors(system_status, SYSTEM_SCHEMA)
    errors += _schema_errors(source_health, SOURCE_SCHEMA)
    errors += _schema_errors(latest, LATEST_SCHEMA)
    if errors:
        raise RuntimeError("Public JSON schema validation failed:\n" + "\n".join(errors))

    geometry_codes = {_feature_metadata(f)[0] for f in geography.get("features", [])}
    latest_codes = {str(row["region_code"]) for row in latest["regions"]}
    if geometry_codes != latest_codes:
        raise RuntimeError(
            "public latest/geography join-key mismatch: "
            f"geometry_only={sorted(geometry_codes - latest_codes)[:10]} "
            f"latest_only={sorted(latest_codes - geometry_codes)[:10]}"
        )

    if system_status["scientific_release"]["risk_engine_allowed"] is not False:
        raise RuntimeError("public system status unexpectedly enables risk")
    if latest["release"]["risk_engine_allowed"] is not False:
        raise RuntimeError("public latest unexpectedly enables risk")
    for row in latest["regions"]:
        if row["risk"] is not None:
            raise RuntimeError(f"risk must be null while locked: {row['region_code']}")
        if row["display_state"] == "RISK_AVAILABLE":
            raise RuntimeError(f"RISK_AVAILABLE forbidden while locked: {row['region_code']}")


def build_public_products(
    *,
    source_health_report_path: Path,
    k2_freeze_path: Path,
    geography_path: Path,
    pipeline_state: str = "PASS",
    run_id: str | None = None,
    commit_sha: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, dict[str, Any]]:
    generated = generated_at_utc or utc_now()
    phase_l = load_json(source_health_report_path)
    k2 = load_json(k2_freeze_path)
    geography = load_json(geography_path)

    verify_phase_l_seal(phase_l)
    k2_state = verify_k2_lock(k2)
    source_health = build_source_health(phase_l, generated_at_utc=generated)
    latest = build_latest(geography, k2_state, generated_at_utc=generated)
    system_status = build_system_status(
        source_health,
        k2_state,
        generated_at_utc=generated,
        pipeline_state=pipeline_state,
        run_id=run_id,
        commit_sha=commit_sha or os.environ.get("GITHUB_SHA") or _git_head(),
    )
    validate_products(
        system_status=system_status,
        source_health=source_health,
        latest=latest,
        geography=geography,
    )
    return {
        "system_status.json": system_status,
        "source_health.json": source_health,
        "latest.json": latest,
    }


def publish_public_products(
    products: dict[str, dict[str, Any]], output_dir: Path
) -> None:
    """Stage all files first; Pages deployment provides the final atomic boundary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="lpz-public-data-", dir=str(output_dir.parent)
    ) as tmpdir:
        staging = Path(tmpdir)
        staged: list[tuple[Path, Path]] = []
        for name, payload in products.items():
            text = json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ) + "\n"
            json.loads(text)
            src = staging / name
            src.write_text(text, encoding="utf-8")
            staged.append((src, output_dir / name))
        for src, dst in staged:
            os.replace(src, dst)
