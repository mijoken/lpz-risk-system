#!/usr/bin/env python3
"""O9-G second half — guarded ERA5 retrieval and reconstruction completion.

Scientific safety boundary:
- no CDS client is created until the real O9-A..F chain, H/K2 freezes, immutable
  92-case population, authorization receipt, request manifest, ERA5 config and
  geometry registry have all been revalidated and SHA-bound;
- retrieval is checkpointed and resumable by immutable request descriptors;
- completion exists only after every frozen request group and all 368 snapshot
  mappings have been reconstructed and validated;
- this stage never runs the frozen Primary and never unlocks the Risk Engine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lpz_risk.era5_multitime import (
    build_time_descriptors,
    decode_era5_pressure_fields_by_time,
    validate_era5_multitime_payload,
)
from lpz_risk.o9_era5_opening import (
    EXPECTED_CASE_COUNT,
    EXPECTED_COMPARISON_COUNT,
    EXPECTED_POSITIVE_COUNT,
    EXPECTED_SNAPSHOT_COUNT,
    sha256_file,
)
from lpz_risk.o9_era5_reconstruction import (
    AUTH_GATE,
    AUTH_PHASE,
    COMPLETE_GATE,
    DESCRIPTOR_PHASE,
    atomic_write_csv,
    atomic_write_json,
    build_cds_request,
    build_completion_receipt,
    build_snapshot_feature_rows,
    collect_valid_descriptors,
    descriptor_filename,
    expected_valid_times,
    read_json,
    validate_request_descriptor,
    validate_request_manifest,
    validate_snapshot_feature_rows,
)
from scripts import o9_g_guarded_era5_opening as opening
from scripts import o9_v08_reentry_harness as harness

CDS_URL = "https://cds.climate.copernicus.eu/api"
CHECKPOINT_PHASE = "O9-G-2025-ERA5-reconstruction-checkpoint"
SNAPSHOT_JSON_PHASE = "O9-G-2025-ERA5-snapshot-feature-table"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_authorization_context(args: argparse.Namespace) -> dict[str, Any]:
    """Revalidate the entire pre-network chain and exact retrieval authorization."""
    chain = opening.verify_real_a_to_f_chain(args.evidence_dir, args.repo_root)
    f_obj = chain["objects"][opening.F_FILE]
    _frame, population_sha = opening.verify_final_population_binding(
        args.final_matched_population, f_obj
    )

    auth = read_json(args.authorization_receipt)
    auth_errors = harness.validate_era5_authorization(auth)
    if auth.get("phase") != AUTH_PHASE:
        auth_errors.append(f"phase must be {AUTH_PHASE}")
    if auth.get("gate") != AUTH_GATE:
        auth_errors.append(f"gate must be {AUTH_GATE}")
    if auth_errors:
        raise ValueError(f"O9-G authorization receipt invalid: {auth_errors}")

    auth_sha = sha256_file(args.authorization_receipt)
    manifest_sha = sha256_file(args.request_manifest)
    config_sha = sha256_file(args.era5_config)
    geometry_sha = sha256_file(args.geometry_registry)

    _require(auth.get("final_matched_population_sha256") == population_sha,
             "authorization receipt no longer binds exact O9-F 92-case population")
    _require(auth.get("request_manifest_sha256") == manifest_sha,
             "authorization receipt request-manifest SHA256 mismatch")
    _require(auth.get("era5_config_sha256") == config_sha,
             "authorization receipt ERA5-config SHA256 mismatch")
    _require(auth.get("geometry_registry_sha256") == geometry_sha,
             "authorization receipt geometry-registry SHA256 mismatch")

    requires = auth.get("requires_sha256") or {}
    for filename, digest in chain["hashes"].items():
        _require(requires.get(filename) == digest,
                 f"authorization receipt predecessor SHA mismatch for {filename}")
    _require(requires.get(harness.H_FREEZE.name) == chain["frozen_protocol"]["h_sha256"],
             "authorization receipt Phase H freeze SHA mismatch")
    _require(requires.get(harness.K2_FREEZE.name) == chain["frozen_protocol"]["k2_sha256"],
             "authorization receipt K2 freeze SHA mismatch")

    manifest = read_json(args.request_manifest)
    validate_request_manifest(manifest)
    embedded = {
        "authorization_gate": manifest.get("authorization_gate") == AUTH_GATE,
        "o9_f_evidence_sha256": manifest.get("o9_f_evidence_sha256") == chain["hashes"][opening.F_FILE],
        "final_matched_population_sha256": manifest.get("final_matched_population_sha256") == population_sha,
        "era5_config_sha256": manifest.get("era5_config_sha256") == config_sha,
        "geometry_registry_sha256": manifest.get("geometry_registry_sha256") == geometry_sha,
    }
    bad = [key for key, ok in embedded.items() if not ok]
    if bad:
        raise ValueError(f"O9-G request manifest provenance mismatch: {bad}")

    return {
        "chain": chain,
        "authorization": auth,
        "authorization_sha256": auth_sha,
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "population_sha256": population_sha,
        "era5_config_sha256": config_sha,
        "geometry_registry_sha256": geometry_sha,
    }


def load_or_initialize_checkpoint(
    path: Path,
    *,
    authorization_sha256: str,
    manifest_sha256: str,
    request_group_count: int,
) -> dict[str, Any]:
    if path.exists():
        cp = read_json(path)
        _require(cp.get("phase") == CHECKPOINT_PHASE, "unexpected O9-G checkpoint phase")
        _require(cp.get("authorization_receipt_sha256") == authorization_sha256,
                 "checkpoint authorization SHA does not match current immutable receipt")
        _require(cp.get("request_manifest_sha256") == manifest_sha256,
                 "checkpoint manifest SHA does not match current immutable manifest")
        _require(int(cp.get("request_group_count", -1)) == request_group_count,
                 "checkpoint request-group count changed")
        _require(cp.get("primary_confirmatory_test_run") is False,
                 "checkpoint unexpectedly says Primary ran")
        _require(cp.get("risk_engine_allowed") is False,
                 "checkpoint unexpectedly allows Risk Engine")
        if not isinstance(cp.get("requests"), dict):
            raise ValueError("O9-G checkpoint requests must be an object")
        return cp

    cp = {
        "schema_version": "1.0.0",
        "phase": CHECKPOINT_PHASE,
        "created_at_utc": utc_now(),
        "updated_at_utc": utc_now(),
        "authorization_receipt_sha256": authorization_sha256,
        "request_manifest_sha256": manifest_sha256,
        "request_group_count": request_group_count,
        "requests": {},
        "completed_request_group_count": 0,
        "failed_request_group_count": 0,
        "complete": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }
    atomic_write_json(path, cp)
    return cp


def update_checkpoint_counts(cp: dict[str, Any]) -> None:
    values = list((cp.get("requests") or {}).values())
    cp["completed_request_group_count"] = sum(x.get("status") == "SUCCESS" for x in values)
    cp["failed_request_group_count"] = sum(x.get("status") == "FAIL" for x in values)
    cp["complete"] = (
        cp["completed_request_group_count"] == int(cp["request_group_count"])
        and cp["failed_request_group_count"] == 0
    )
    cp["updated_at_utc"] = utc_now()
    cp["primary_confirmatory_test_run"] = False
    cp["risk_engine_allowed"] = False
    cp["public_risk_release_allowed"] = False


def create_cds_client() -> Any:
    """Network boundary.  Called only after verify_authorization_context passes."""
    key = os.environ.get("CDSAPI_KEY", "").strip()
    if not key:
        raise RuntimeError("CDSAPI_KEY is required after O9-G authorization")
    import cdsapi  # intentionally lazy: no CDS library use before the gate

    return cdsapi.Client(url=CDS_URL, key=key, quiet=False)


def retrieve_one_request(
    *,
    client: Any,
    index: int,
    group: dict[str, Any],
    descriptor_root: Path,
    work_dir: Path,
    authorization_sha256: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Retrieve, decode, validate and freeze one request descriptor."""
    request_id = str(group["request_id"])
    descriptor_path = descriptor_root / descriptor_filename(index, request_id)
    if descriptor_path.exists():
        obj = read_json(descriptor_path)
        validate_request_descriptor(
            obj,
            index=index,
            group=group,
            authorization_sha256=authorization_sha256,
            manifest_sha256=manifest_sha256,
        )
        return obj

    work_dir.mkdir(parents=True, exist_ok=True)
    descriptor_root.mkdir(parents=True, exist_ok=True)
    grib_path = work_dir / f"{index:04d}_{request_id}.grib"
    if grib_path.exists():
        grib_path.unlink()

    started = utc_now()
    try:
        client.retrieve(group["dataset"], build_cds_request(group), str(grib_path))
        if not grib_path.exists() or grib_path.stat().st_size <= 0:
            raise RuntimeError(f"empty ERA5 GRIB payload for {request_id}")
        payload_bytes = grib_path.read_bytes()
        payload_sha = sha256_bytes(payload_bytes)
        downloaded_bytes = len(payload_bytes)

        fields_by_time = decode_era5_pressure_fields_by_time(grib_path)
        expected = expected_valid_times(group)
        validation = validate_era5_multitime_payload(fields_by_time, expected)
        if validation.get("multitime_payload_pass") is not True:
            raise ValueError(f"ERA5 multi-time validation failed for {request_id}: {validation}")
        time_descriptors = build_time_descriptors(fields_by_time)

        descriptor = {
            "schema_version": "1.0.0",
            "phase": DESCRIPTOR_PHASE,
            "request_index": index,
            "request_id": request_id,
            "date_utc": group["date_utc"],
            "primary_subdivision_code": str(group["primary_subdivision_code"]).zfill(6),
            "times_utc": list(group["times_utc"]),
            "pressure_levels_hpa": list(group["pressure_levels_hpa"]),
            "variables": list(group["variables"]),
            "cds_area_north_west_south_east": list(group["area_nwse"]),
            "spatial_semantics": group["spatial_semantics"],
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "authorization_receipt_sha256": authorization_sha256,
            "request_manifest_sha256": manifest_sha256,
            "downloaded_bytes": downloaded_bytes,
            "payload_sha256": payload_sha,
            "multitime_validation": validation,
            "time_descriptors": time_descriptors,
            "network_access_performed": True,
            "era5_environment_values_read": True,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
            "public_risk_release_allowed": False,
        }
        validate_request_descriptor(
            descriptor,
            index=index,
            group=group,
            authorization_sha256=authorization_sha256,
            manifest_sha256=manifest_sha256,
        )
        atomic_write_json(descriptor_path, descriptor)
        return descriptor
    finally:
        if grib_path.exists():
            grib_path.unlink()


def _snapshot_payload(rows: list[dict[str, Any]], *, context: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "phase": SNAPSHOT_JSON_PHASE,
        "validation_year": 2025,
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "matched_case_count": EXPECTED_CASE_COUNT,
        "positive_case_count": EXPECTED_POSITIVE_COUNT,
        "comparison_case_count": EXPECTED_COMPARISON_COUNT,
        "snapshot_feature_row_count": EXPECTED_SNAPSHOT_COUNT,
        "authorization_receipt_sha256": context["authorization_sha256"],
        "request_manifest_sha256": context["manifest_sha256"],
        "matching_membership_changed_by_era5": False,
        "environment_variables_used_for_matching_membership": False,
        "future_source_time_count": 0,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
        "snapshot_features": rows,
    }


def write_or_verify_final_features(
    *,
    rows: list[dict[str, Any]],
    csv_path: Path,
    json_path: Path,
    context: dict[str, Any],
) -> None:
    validate_snapshot_feature_rows(rows)
    payload = _snapshot_payload(rows, context=context)

    if csv_path.exists():
        import pandas as pd
        existing = pd.read_csv(csv_path, dtype={"primary_subdivision_code": "string"})
        expected = pd.DataFrame(rows)
        existing["primary_subdivision_code"] = existing["primary_subdivision_code"].astype("string").str.zfill(6)
        expected["primary_subdivision_code"] = expected["primary_subdivision_code"].astype("string").str.zfill(6)
        _require(list(existing.columns) == list(expected.columns), "existing final snapshot CSV schema differs")
        _require(existing.fillna("").astype(str).equals(expected.fillna("").astype(str)),
                 "existing final snapshot CSV differs from reconstructed immutable rows")
    else:
        atomic_write_csv(csv_path, rows)

    if json_path.exists():
        existing_json = read_json(json_path)
        _require(existing_json == payload, "existing final snapshot JSON differs from reconstructed immutable payload")
    else:
        atomic_write_json(json_path, payload)


def run(
    args: argparse.Namespace,
    *,
    client_factory: Callable[[], Any] = create_cds_client,
    retrieve_fn: Callable[..., dict[str, Any]] = retrieve_one_request,
) -> int:
    if args.completion_receipt_output.exists():
        raise FileExistsError(
            f"immutable O9-G completion receipt already exists: {args.completion_receipt_output}"
        )

    # CRITICAL: everything below must pass before client_factory can run.
    context = verify_authorization_context(args)
    manifest = context["manifest"]
    request_groups = manifest["request_groups"]

    cp = load_or_initialize_checkpoint(
        args.checkpoint,
        authorization_sha256=context["authorization_sha256"],
        manifest_sha256=context["manifest_sha256"],
        request_group_count=len(request_groups),
    )

    valid, missing = collect_valid_descriptors(
        descriptor_root=args.descriptor_root,
        manifest=manifest,
        authorization_sha256=context["authorization_sha256"],
        manifest_sha256=context["manifest_sha256"],
    )
    for index, descriptor in valid.items():
        cp["requests"][str(index)] = {
            "request_id": descriptor["request_id"],
            "status": "SUCCESS",
            "descriptor_path": str(args.descriptor_root / descriptor_filename(index, descriptor["request_id"])),
            "downloaded_bytes": int(descriptor["downloaded_bytes"]),
            "payload_sha256": descriptor["payload_sha256"],
        }
    update_checkpoint_counts(cp)
    atomic_write_json(args.checkpoint, cp)

    cap = int(args.max_new_requests)
    to_process = missing if cap == 0 else missing[:cap]
    if to_process:
        client = client_factory()
        for index in to_process:
            group = request_groups[index]
            rec = {
                "request_id": group["request_id"],
                "status": "RUNNING",
                "started_at_utc": utc_now(),
            }
            cp["requests"][str(index)] = rec
            update_checkpoint_counts(cp)
            atomic_write_json(args.checkpoint, cp)
            try:
                descriptor = retrieve_fn(
                    client=client,
                    index=index,
                    group=group,
                    descriptor_root=args.descriptor_root,
                    work_dir=args.work_dir,
                    authorization_sha256=context["authorization_sha256"],
                    manifest_sha256=context["manifest_sha256"],
                )
                rec.update({
                    "status": "SUCCESS",
                    "completed_at_utc": utc_now(),
                    "descriptor_path": str(args.descriptor_root / descriptor_filename(index, group["request_id"])),
                    "downloaded_bytes": int(descriptor["downloaded_bytes"]),
                    "payload_sha256": descriptor["payload_sha256"],
                })
            except Exception as exc:  # noqa: BLE001
                rec.update({
                    "status": "FAIL",
                    "completed_at_utc": utc_now(),
                    "error": f"{type(exc).__name__}: {exc}",
                })
            finally:
                cp["requests"][str(index)] = rec
                update_checkpoint_counts(cp)
                atomic_write_json(args.checkpoint, cp)

    valid, missing_after = collect_valid_descriptors(
        descriptor_root=args.descriptor_root,
        manifest=manifest,
        authorization_sha256=context["authorization_sha256"],
        manifest_sha256=context["manifest_sha256"],
    )
    cp["missing_request_indices"] = missing_after
    update_checkpoint_counts(cp)
    # True scientific completion depends on validated descriptor census, not stale fail history.
    cp["completed_request_group_count"] = len(valid)
    cp["complete"] = len(valid) == len(request_groups) and not missing_after
    atomic_write_json(args.checkpoint, cp)

    if missing_after:
        print(json.dumps({
            "state": "INCOMPLETE_O9_G_ERA5_RECONSTRUCTION_RESUMABLE",
            "request_groups_complete": len(valid),
            "request_groups_expected": len(request_groups),
            "missing_request_groups": len(missing_after),
            "completion_receipt_created": False,
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
        }))
        return 3

    rows = build_snapshot_feature_rows(manifest=manifest, descriptors=valid)
    write_or_verify_final_features(
        rows=rows,
        csv_path=args.snapshot_csv_output,
        json_path=args.snapshot_json_output,
        context=context,
    )

    receipt = build_completion_receipt(
        authorization_receipt_path=args.authorization_receipt,
        manifest_path=args.request_manifest,
        snapshot_csv_path=args.snapshot_csv_output,
        snapshot_json_path=args.snapshot_json_output,
        descriptor_root=args.descriptor_root,
        manifest=manifest,
        descriptor_count=len(valid),
        generated_at_utc=utc_now(),
    )
    # Reassert direct authorization binding expected by the global O9 harness.
    receipt["requires_sha256"] = {
        args.authorization_receipt.name: context["authorization_sha256"],
        args.request_manifest.name: context["manifest_sha256"],
    }
    atomic_write_json(args.completion_receipt_output, receipt)

    print(json.dumps({
        "gate": COMPLETE_GATE,
        "matched_cases": EXPECTED_CASE_COUNT,
        "snapshot_features": EXPECTED_SNAPSHOT_COUNT,
        "request_groups": len(request_groups),
        "primary_confirmatory_test_run": False,
        "confirmatory_run_may_execute": True,
        "risk_engine_allowed": False,
    }))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=harness.ROOT)
    ap.add_argument("--evidence-dir", required=True, type=Path)
    ap.add_argument("--final-matched-population", required=True, type=Path)
    ap.add_argument("--authorization-receipt", required=True, type=Path)
    ap.add_argument("--request-manifest", required=True, type=Path)
    ap.add_argument("--era5-config", type=Path, default=Path("config/historical_environment_era5.json"))
    ap.add_argument("--geometry-registry", type=Path, default=Path("research/phase2/primary_subdivision_geometry_registry_20260909.json"))
    ap.add_argument("--descriptor-root", required=True, type=Path)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--snapshot-csv-output", required=True, type=Path)
    ap.add_argument("--snapshot-json-output", required=True, type=Path)
    ap.add_argument("--completion-receipt-output", required=True, type=Path)
    ap.add_argument("--max-new-requests", type=int, default=0, help="0 means process all missing request groups")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    if args.max_new_requests < 0:
        raise SystemExit("--max-new-requests must be >=0")
    if not args.era5_config.is_absolute():
        args.era5_config = args.repo_root / args.era5_config
    if not args.geometry_registry.is_absolute():
        args.geometry_registry = args.repo_root / args.geometry_registry
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
