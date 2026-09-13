from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from lpz_risk.o9_era5_reconstruction import (
    COMPLETE_GATE,
    DESCRIPTOR_PHASE,
    atomic_write_json,
    build_snapshot_feature_rows,
    descriptor_filename,
    expected_valid_times,
    validate_request_manifest,
)
from scripts import o9_g_guarded_era5_opening as opening
from scripts import o9_g_guarded_era5_reconstruction as runner
from scripts import o9_v08_reentry_harness as harness


def _auth_support():
    path = harness.ROOT / "tests/test_o9_g_guarded_era5_opening.py"
    spec = importlib.util.spec_from_file_location("o9_auth_test_support", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_real_style_authorization(tmp_path: Path):
    support = _auth_support()
    population_csv = tmp_path / "o9_f_final_matched_population.csv"
    support._population().to_csv(population_csv, index=False)
    evidence = support._seed_a_to_f(tmp_path, population_csv)
    auth_args = support._args(tmp_path, evidence, population_csv)
    assert opening.run(auth_args) == 0
    return population_csv, evidence, auth_args


def _runner_args(tmp_path: Path, population_csv: Path, evidence: Path, auth_args) -> argparse.Namespace:
    return argparse.Namespace(
        repo_root=harness.ROOT,
        evidence_dir=evidence,
        final_matched_population=population_csv,
        authorization_receipt=auth_args.receipt_output,
        request_manifest=auth_args.manifest_output,
        era5_config=harness.ROOT / "config/historical_environment_era5.json",
        geometry_registry=harness.ROOT / "research/phase2/primary_subdivision_geometry_registry_20260909.json",
        descriptor_root=tmp_path / "descriptors",
        checkpoint=tmp_path / "checkpoint.json",
        work_dir=tmp_path / "work",
        snapshot_csv_output=tmp_path / "o9_g_era5_snapshot_features.csv",
        snapshot_json_output=tmp_path / "o9_g_era5_snapshot_features.json",
        completion_receipt_output=evidence / "o9_g_2025_era5_reconstruction_complete.json",
        max_new_requests=0,
    )


def _env(seed: float = 0.0) -> dict:
    return {
        "source": "ERA5",
        "exactness": "PROXY_REANALYSIS",
        "grid_points": 25,
        "rh500_mean_pct": 60.0 + seed,
        "rh700_mean_pct": 70.0 + seed,
        "rh500_rh700_gt60_fraction": 0.4,
        "rh_supersaturation_note": "synthetic unit-test descriptor only",
        "wind600_speed_mean_mps": 10.0,
        "wind600_from_direction_median_deg": 180.0,
        "wind850_speed_mean_mps": 8.0,
        "wind850_from_direction_median_deg": 190.0,
        "specific_humidity_mean_kgkg": {
            "1000": 0.012 + seed * 1e-6,
            "925": 0.010 + seed * 1e-6,
            "850": 0.008 + seed * 1e-6,
        },
        "spatial_semantics": "REQUEST_BBOX_CONTEXT_NOT_SUBDIVISION_POLYGON_MEAN",
        "risk_score": None,
    }


def _descriptor(index: int, group: dict, auth_sha: str, manifest_sha: str) -> dict:
    times = expected_valid_times(group)
    rows = []
    for j, source_time in enumerate(times):
        rows.append({
            "era5_source_time_utc": source_time,
            "validation": {
                "required_field_count": 9,
                "present_required_field_count": 9,
                "missing_required_fields": [],
                "invalid_required_fields": [],
                "required_fields_pass": True,
                "risk_engine_allowed": False,
            },
            "environment_descriptors": _env(float(index + j) / 100.0),
        })
    return {
        "schema_version": "1.0.0",
        "phase": DESCRIPTOR_PHASE,
        "request_index": index,
        "request_id": group["request_id"],
        "date_utc": group["date_utc"],
        "primary_subdivision_code": str(group["primary_subdivision_code"]).zfill(6),
        "times_utc": list(group["times_utc"]),
        "pressure_levels_hpa": list(group["pressure_levels_hpa"]),
        "variables": list(group["variables"]),
        "cds_area_north_west_south_east": list(group["area_nwse"]),
        "spatial_semantics": group["spatial_semantics"],
        "started_at_utc": "2026-09-14T00:00:00Z",
        "completed_at_utc": "2026-09-14T00:00:01Z",
        "authorization_receipt_sha256": auth_sha,
        "request_manifest_sha256": manifest_sha,
        "downloaded_bytes": 12345,
        "payload_sha256": f"{index + 1:064x}"[-64:],
        "multitime_validation": {
            "expected_valid_time_count": len(times),
            "decoded_valid_time_count": len(times),
            "decoded_valid_times_utc": times,
            "missing_valid_times_utc": [],
            "unexpected_valid_times_utc": [],
            "failed_field_validation_times_utc": [],
            "multitime_payload_pass": True,
            "risk_engine_allowed": False,
        },
        "time_descriptors": rows,
        "network_access_performed": True,
        "era5_environment_values_read": True,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
        "public_risk_release_allowed": False,
    }


def _seed_all_descriptors(args: argparse.Namespace) -> dict:
    context = runner.verify_authorization_context(args)
    args.descriptor_root.mkdir(parents=True, exist_ok=True)
    for index, group in enumerate(context["manifest"]["request_groups"]):
        obj = _descriptor(index, group, context["authorization_sha256"], context["manifest_sha256"])
        atomic_write_json(args.descriptor_root / descriptor_filename(index, group["request_id"]), obj)
    return context


class BombClientFactory:
    def __init__(self):
        self.called = False

    def __call__(self):
        self.called = True
        raise AssertionError("CDS client must not be created before all guards pass")


def test_manifest_exact_92_by_4_contract(tmp_path: Path):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    args = _runner_args(tmp_path, population, evidence, auth_args)
    context = runner.verify_authorization_context(args)
    manifest = validate_request_manifest(context["manifest"])
    assert manifest["matched_case_count"] == 92
    assert manifest["positive_case_count"] == 23
    assert manifest["comparison_case_count"] == 69
    assert manifest["snapshot_mapping_count"] == 368
    assert len(manifest["snapshot_mappings"]) == 368
    frame = pd.DataFrame(manifest["snapshot_mappings"])
    counts = frame.groupby(["match_set_id", "match_rank"]).size()
    assert len(counts) == 92
    assert set(counts.tolist()) == {4}
    assert set(frame["snapshot_offset_hours"].astype(int)) == {-12, -6, -3, 0}


def test_manifest_rejects_future_source_time(tmp_path: Path):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    manifest = json.loads(auth_args.manifest_output.read_text(encoding="utf-8"))
    m = manifest["snapshot_mappings"][0]
    requested = pd.Timestamp(m["requested_snapshot_time_utc"])
    m["era5_source_time_utc"] = (requested + pd.Timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    with pytest.raises(ValueError, match="future ERA5"):
        validate_request_manifest(manifest)


def test_manifest_rejects_request_group_coverage_gap(tmp_path: Path):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    manifest = json.loads(auth_args.manifest_output.read_text(encoding="utf-8"))
    manifest["request_groups"][0]["times_utc"] = manifest["request_groups"][0]["times_utc"][1:]
    with pytest.raises(ValueError, match="exactly cover"):
        validate_request_manifest(manifest)


@pytest.mark.parametrize("mutation", ["authorization", "manifest", "evidence", "population", "checkpoint"])
def test_fail_closed_before_client_factory(tmp_path: Path, mutation: str):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    args = _runner_args(tmp_path, population, evidence, auth_args)

    if mutation == "authorization":
        obj = json.loads(args.authorization_receipt.read_text(encoding="utf-8"))
        obj["matched_case_count"] = 91
        args.authorization_receipt.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    elif mutation == "manifest":
        obj = json.loads(args.request_manifest.read_text(encoding="utf-8"))
        obj["tampered_after_authorization"] = True
        args.request_manifest.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    elif mutation == "evidence":
        cpath = evidence / opening.C_FILE
        obj = json.loads(cpath.read_text(encoding="utf-8"))
        obj["tampered_after_authorization"] = True
        cpath.write_text(json.dumps(obj) + "\n", encoding="utf-8")
    elif mutation == "population":
        with population.open("a", encoding="utf-8") as f:
            f.write("\n")
    elif mutation == "checkpoint":
        context = runner.verify_authorization_context(args)
        runner.atomic_write_json(args.checkpoint, {
            "schema_version": "1.0.0",
            "phase": runner.CHECKPOINT_PHASE,
            "authorization_receipt_sha256": "0" * 64,
            "request_manifest_sha256": context["manifest_sha256"],
            "request_group_count": len(context["manifest"]["request_groups"]),
            "requests": {},
            "primary_confirmatory_test_run": False,
            "risk_engine_allowed": False,
        })

    bomb = BombClientFactory()
    with pytest.raises((ValueError, FileNotFoundError)):
        runner.run(args, client_factory=bomb)
    assert bomb.called is False


def test_complete_preseeded_descriptors_builds_368_rows_and_receipt_without_client(tmp_path: Path):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    args = _runner_args(tmp_path, population, evidence, auth_args)
    context = _seed_all_descriptors(args)
    bomb = BombClientFactory()
    assert runner.run(args, client_factory=bomb) == 0
    assert bomb.called is False

    completion = json.loads(args.completion_receipt_output.read_text(encoding="utf-8"))
    assert completion["gate"] == COMPLETE_GATE
    assert completion["era5_retrieval_completed"] is True
    assert completion["matched_case_count"] == 92
    assert completion["snapshot_mapping_count"] == 368
    assert completion["missing_snapshot_count"] == 0
    assert completion["future_source_time_count"] == 0
    assert completion["primary_confirmatory_test_run"] is False
    assert completion["confirmatory_run_may_execute"] is True
    assert completion["risk_engine_allowed"] is False
    assert completion["public_risk_release_allowed"] is False
    assert completion["requires_sha256"][args.authorization_receipt.name] == context["authorization_sha256"]

    features = json.loads(args.snapshot_json_output.read_text(encoding="utf-8"))
    assert features["snapshot_feature_row_count"] == 368
    assert len(features["snapshot_features"]) == 368
    rows = features["snapshot_features"]
    assert all(r["risk_score"] is None for r in rows)
    assert all(pd.Timestamp(r["era5_source_time_utc"]) <= pd.Timestamp(r["requested_snapshot_time_utc"]) for r in rows)

    # Temporary real-style chain now reaches exactly the Primary eligibility boundary.
    shutil_target = evidence / args.authorization_receipt.name
    shutil_target.write_bytes(args.authorization_receipt.read_bytes())
    state = harness.evaluate_chain(harness.ROOT, evidence)
    assert state["state"] == "READY_FOR_SINGLE_FROZEN_PRIMARY_CONFIRMATORY_RUN"
    assert state["confirmatory_run_may_execute"] is True
    assert state["risk_engine_allowed"] is False
    assert state["public_risk_release_allowed"] is False


def test_partial_fake_retrieval_is_resumable_and_does_not_complete(tmp_path: Path):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    args = _runner_args(tmp_path, population, evidence, auth_args)
    args.max_new_requests = 2
    context = runner.verify_authorization_context(args)
    calls = {"client": 0, "retrieve": 0}

    def fake_client_factory():
        calls["client"] += 1
        return object()

    def fake_retrieve(**kwargs):
        calls["retrieve"] += 1
        index = kwargs["index"]
        group = kwargs["group"]
        obj = _descriptor(index, group, kwargs["authorization_sha256"], kwargs["manifest_sha256"])
        kwargs["descriptor_root"].mkdir(parents=True, exist_ok=True)
        atomic_write_json(kwargs["descriptor_root"] / descriptor_filename(index, group["request_id"]), obj)
        return obj

    assert runner.run(args, client_factory=fake_client_factory, retrieve_fn=fake_retrieve) == 3
    assert calls == {"client": 1, "retrieve": 2}
    assert not args.completion_receipt_output.exists()
    cp = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    assert cp["completed_request_group_count"] == 2
    assert cp["complete"] is False

    # A second bounded run resumes from the next missing requests rather than redoing two.
    assert runner.run(args, client_factory=fake_client_factory, retrieve_fn=fake_retrieve) == 3
    assert calls == {"client": 2, "retrieve": 4}
    cp2 = json.loads(args.checkpoint.read_text(encoding="utf-8"))
    assert cp2["completed_request_group_count"] == 4


def test_build_snapshot_rows_rejects_missing_descriptor(tmp_path: Path):
    population, evidence, auth_args = _build_real_style_authorization(tmp_path)
    args = _runner_args(tmp_path, population, evidence, auth_args)
    context = _seed_all_descriptors(args)
    valid, missing = runner.collect_valid_descriptors(
        descriptor_root=args.descriptor_root,
        manifest=context["manifest"],
        authorization_sha256=context["authorization_sha256"],
        manifest_sha256=context["manifest_sha256"],
    )
    assert not missing
    valid.pop(next(iter(valid)))
    with pytest.raises(ValueError, match="missing reconstructed ERA5 source"):
        build_snapshot_feature_rows(manifest=context["manifest"], descriptors=valid)
