from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from itertools import islice, product
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lpz_risk.canonical_rainfall import CanonicalRainfallField
from lpz_risk.o9_v08_rebuild import (
    EXPECTED_ROLLING_WINDOWS,
    EXPECTED_SLOT_COUNT,
    compute_metrics_from_slot_amounts,
    compute_region_day_metrics,
    expected_rolling_starts,
    expected_slot_starts,
    validate_exact_v08_fields,
)
from scripts import o9_v08_rainfall_rebuild as orch


def make_fields(day: str, *, rate_mm_per_hr: float = 2.0) -> list[CanonicalRainfallField]:
    fields: list[CanonicalRainfallField] = []
    lon = np.array([139.0, 140.0], dtype=float)
    lat = np.array([35.0, 36.0], dtype=float)
    for i, start in enumerate(expected_slot_starts(day)):
        fields.append(
            CanonicalRainfallField(
                source_id="NASA_IMERG_FINAL_V08",
                product_version="08",
                valid_start_utc=start,
                valid_end_utc=start + timedelta(minutes=30),
                accumulation_seconds=1800,
                rain_rate_mm_per_hr=np.full((2, 2), rate_mm_per_hr, dtype=float),
                longitude_deg_e=lon,
                latitude_deg_n=lat,
                gauge_adjusted=True,
                source_path=f"synthetic_{i:02d}.V08A.HDF5",
            )
        )
    return fields


def make_population_rows(*, start: str, end: str, count: int, codes: int) -> list[dict[str, object]]:
    dates = pd.date_range(start, end, freq="D").strftime("%Y-%m-%d").tolist()
    code_values = [f"{i:06d}" for i in range(1, codes + 1)]
    pairs = islice(product(dates, code_values), count)
    return [
        {"date_utc": day, "primary_subdivision_code": code}
        for day, code in pairs
    ]


def checkpoint_row(day: str, code: str, value: float = 6.0) -> dict[str, object]:
    first = expected_rolling_starts(day)[0].isoformat()
    end = (expected_rolling_starts(day)[0] + timedelta(hours=3)).isoformat()
    row: dict[str, object] = {
        "date_utc": day,
        "primary_subdivision_code": code,
        "rolling_window_count": EXPECTED_ROLLING_WINDOWS,
    }
    for stat in ("mean", "max", "p90", "p95"):
        row[f"imerg_3h_{stat}_max_mm"] = value
        row[f"imerg_3h_{stat}_window_start_utc"] = first
        row[f"imerg_3h_{stat}_window_end_utc"] = end
    return row


def write_valid_checkpoint(
    path: Path,
    *,
    split: str,
    day: str,
    codes: list[str],
    target_sha: str,
    coverage_sha: str,
) -> None:
    payload = {
        "schema_version": "1.0.0",
        "phase": "O9-D-V08-rainfall-rebuild-daily",
        "gate": orch.DAILY_GATE,
        "engine_contract": orch.ENGINE_CONTRACT,
        "split": split,
        "date_utc": day,
        "source_id": orch.SOURCE_ID,
        "short_name": orch.SHORT_NAME,
        "imerg_final_version": orch.IMERG_VERSION,
        "official_final_product": True,
        "expected_slot_count": EXPECTED_SLOT_COUNT,
        "available_slot_count": EXPECTED_SLOT_COUNT,
        "missing_slots": [],
        "rolling_window_count_per_region_day": EXPECTED_ROLLING_WINDOWS,
        "target_csv_sha256": target_sha,
        "coverage_evidence_sha256": coverage_sha,
        "downloaded_source_bytes": 0,
        "rows": [checkpoint_row(day, code) for code in codes],
        "environment_variables_used": False,
        "validation_era5_environment_read": False,
        "matching_performed": False,
        "pca_fit_performed": False,
        "primary_confirmatory_test_run": False,
        "risk_engine_allowed": False,
    }
    orch.atomic_write_json(path, payload)


def test_exact_58_slots_and_53_rolling_boundaries() -> None:
    day = "2024-05-10"
    slots = expected_slot_starts(day)
    rolling = expected_rolling_starts(day)
    assert len(slots) == EXPECTED_SLOT_COUNT == 58
    assert len(rolling) == EXPECTED_ROLLING_WINDOWS == 53
    assert slots[0].isoformat() == "2024-05-09T21:30:00+00:00"
    assert slots[-1].isoformat() == "2024-05-11T02:00:00+00:00"
    assert rolling[0].isoformat() == "2024-05-09T21:30:00+00:00"
    assert rolling[-1].isoformat() == "2024-05-10T23:30:00+00:00"


def test_constant_rain_produces_exact_3h_total_and_earliest_tie() -> None:
    day = "2024-05-10"
    # 2 mm/hr over each 30-minute interval = 1 mm per slot; six slots = 6 mm.
    slots = [np.ones((2, 2), dtype=float) for _ in range(EXPECTED_SLOT_COUNT)]
    out = compute_metrics_from_slot_amounts(day=day, slot_amounts_mm=slots)
    assert out["rolling_window_count"] == EXPECTED_ROLLING_WINDOWS
    for stat in ("mean", "max", "p90", "p95"):
        assert out[f"imerg_3h_{stat}_max_mm"] == pytest.approx(6.0)
        assert out[f"imerg_3h_{stat}_window_start_utc"] == "2024-05-09T21:30:00+00:00"
        assert out[f"imerg_3h_{stat}_window_end_utc"] == "2024-05-10T00:30:00+00:00"


def test_last_slot_peak_selects_last_rolling_window() -> None:
    day = "2024-05-10"
    slots = [np.zeros((2, 2), dtype=float) for _ in range(EXPECTED_SLOT_COUNT)]
    slots[-1][:] = 10.0
    out = compute_metrics_from_slot_amounts(day=day, slot_amounts_mm=slots)
    for stat in ("mean", "max", "p90", "p95"):
        assert out[f"imerg_3h_{stat}_max_mm"] == pytest.approx(10.0)
        assert out[f"imerg_3h_{stat}_window_start_utc"] == "2024-05-10T23:30:00+00:00"
        assert out[f"imerg_3h_{stat}_window_end_utc"] == "2024-05-11T02:30:00+00:00"


def test_region_field_entry_point_matches_amount_engine() -> None:
    day = "2024-05-10"
    fields = make_fields(day, rate_mm_per_hr=2.0)
    out = compute_region_day_metrics(
        day=day,
        fields=fields,
        bbox_wsen=(139.0, 35.0, 140.0, 36.0),
    )
    assert out["source_id"] == "NASA_IMERG_FINAL_V08"
    assert out["imerg_final_version"] == "08"
    assert out["imerg_3h_mean_max_mm"] == pytest.approx(6.0)
    assert out["imerg_3h_max_max_mm"] == pytest.approx(6.0)


def test_v07_field_is_rejected_before_science() -> None:
    day = "2024-05-10"
    fields = make_fields(day)
    fields[7] = replace(
        fields[7],
        source_id="NASA_IMERG_FINAL_V07",
        product_version="07",
    )
    with pytest.raises(ValueError, match="non-V08 field"):
        validate_exact_v08_fields(day, fields)


def test_missing_slot_and_shape_change_are_rejected() -> None:
    day = "2024-05-10"
    fields = make_fields(day)
    with pytest.raises(ValueError, match="expected 58"):
        validate_exact_v08_fields(day, fields[:-1])

    bad_amounts = [np.zeros((2, 2), dtype=float) for _ in range(EXPECTED_SLOT_COUNT)]
    bad_amounts[30] = np.zeros((3, 2), dtype=float)
    with pytest.raises(ValueError, match="shape changed"):
        compute_metrics_from_slot_amounts(day=day, slot_amounts_mm=bad_amounts)


def test_development_population_contract_is_exactly_5943(tmp_path: Path) -> None:
    rows = make_population_rows(
        start="2023-01-01",
        end="2024-12-31",
        count=5943,
        codes=9,
    )
    path = tmp_path / "dev.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    got = orch.read_targets(path, "DEVELOPMENT")
    assert len(got) == 5943
    assert set(pd.to_datetime(got["date_utc"]).dt.year) == {2023, 2024}

    pd.DataFrame(rows[:-1]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="target count must be 5943"):
        orch.read_targets(path, "DEVELOPMENT")


def test_validation_population_contract_is_1218_and_23_positive(tmp_path: Path) -> None:
    rows = make_population_rows(
        start="2025-01-01",
        end="2025-12-31",
        count=1218,
        codes=4,
    )
    for i, row in enumerate(rows):
        row["is_official_positive"] = i < 23
    path = tmp_path / "validation.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    got = orch.read_targets(path, "VALIDATION_2025")
    assert len(got) == 1218
    assert int(got["is_official_positive"].sum()) == 23

    rows[22]["is_official_positive"] = False
    pd.DataFrame(rows).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Positive count must be 23"):
        orch.read_targets(path, "VALIDATION_2025")


def test_o9_c_coverage_gate_must_be_exact_and_risk_locked(tmp_path: Path) -> None:
    path = tmp_path / "o9_c_v08_required_coverage.json"
    payload = {
        "gate": orch.COVERAGE_GATE,
        "short_name": orch.SHORT_NAME,
        "imerg_final_version": "08",
        "official_final_product": True,
        "development_region_day_count": 5943,
        "validation_region_day_count": 1218,
        "development_missing_slot_count": 0,
        "validation_missing_slot_count": 0,
        "all_required_slots_covered": True,
        "risk_engine_allowed": False,
    }
    orch.atomic_write_json(path, payload)
    meta = orch.verify_coverage_evidence(path)
    assert meta["checks"]["all_covered"] is True

    payload["validation_missing_slot_count"] = 1
    orch.atomic_write_json(path, payload)
    with pytest.raises(ValueError, match="not PASS-compatible"):
        orch.verify_coverage_evidence(path)


def test_synthetic_process_day_writes_valid_checkpoint_and_resume_skips_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    day = "2025-07-15"
    code = "130010"
    fields = make_fields(day, rate_mm_per_hr=2.0)
    raw_dir = tmp_path / "synthetic_raw"
    raw_dir.mkdir()
    mapping: dict[object, Path] = {}
    by_path: dict[Path, CanonicalRainfallField] = {}
    for i, (start, field) in enumerate(zip(expected_slot_starts(day), fields, strict=True)):
        p = raw_dir / f"slot_{i:02d}.synthetic"
        p.write_bytes(b"x" * 2048)
        mapping[start] = p
        by_path[p] = field

    monkeypatch.setattr(orch, "download_v08_slots", lambda _day, _dest: mapping)
    monkeypatch.setattr(
        orch,
        "decode_imerg_final_file",
        lambda path, expected_version=None: by_path[Path(path)],
    )

    targets = pd.DataFrame([
        {
            "date_utc": day,
            "primary_subdivision_code": code,
            "is_official_positive": False,
            "selected_by_frozen_cmorph_screen": True,
            "refinement_role": "SYNTHETIC_PROOF",
        }
    ])
    outdir = tmp_path / "out"
    temp_root = tmp_path / "work"
    result = orch.process_day(
        split="VALIDATION_2025",
        date_s=day,
        day_targets=targets,
        windows={code: (139.0, 35.0, 140.0, 36.0)},
        outdir=outdir,
        temp_root=temp_root,
        target_sha256="target-sha",
        coverage_sha256="coverage-sha",
    )
    assert result["status"] == "SUCCESS"

    cp = orch.checkpoint_path(outdir, "VALIDATION_2025", day)
    obj = orch.validate_checkpoint(
        cp,
        split="VALIDATION_2025",
        date_s=day,
        expected_codes=[code],
        target_sha256="target-sha",
        coverage_sha256="coverage-sha",
    )
    assert obj is not None
    assert obj["validation_era5_environment_read"] is False
    assert obj["matching_performed"] is False
    assert obj["pca_fit_performed"] is False
    assert obj["primary_confirmatory_test_run"] is False
    assert obj["risk_engine_allowed"] is False
    assert obj["rows"][0]["imerg_3h_mean_max_mm"] == pytest.approx(6.0)

    def forbidden_download(*_args, **_kwargs):
        raise AssertionError("resume attempted a network download despite valid checkpoint")

    monkeypatch.setattr(orch, "download_v08_slots", forbidden_download)
    resumed = orch.process_day(
        split="VALIDATION_2025",
        date_s=day,
        day_targets=targets,
        windows={code: (139.0, 35.0, 140.0, 36.0)},
        outdir=outdir,
        temp_root=temp_root,
        target_sha256="target-sha",
        coverage_sha256="coverage-sha",
    )
    assert resumed["status"] == "SKIP_VALID_CHECKPOINT"
    assert resumed["downloaded_bytes"] == 0


def test_resume_invalidates_checkpoint_when_upstream_hash_changes(tmp_path: Path) -> None:
    day = "2025-07-15"
    code = "130010"
    cp = orch.checkpoint_path(tmp_path, "VALIDATION_2025", day)
    write_valid_checkpoint(
        cp,
        split="VALIDATION_2025",
        day=day,
        codes=[code],
        target_sha="target-A",
        coverage_sha="coverage-A",
    )
    assert orch.validate_checkpoint(
        cp,
        split="VALIDATION_2025",
        date_s=day,
        expected_codes=[code],
        target_sha256="target-A",
        coverage_sha256="coverage-A",
    ) is not None
    assert orch.validate_checkpoint(
        cp,
        split="VALIDATION_2025",
        date_s=day,
        expected_codes=[code],
        target_sha256="target-B",
        coverage_sha256="coverage-A",
    ) is None


def test_collect_checkpoints_reports_only_missing_dates(tmp_path: Path) -> None:
    targets = pd.DataFrame([
        {"date_utc": "2025-07-15", "primary_subdivision_code": "130010"},
        {"date_utc": "2025-07-16", "primary_subdivision_code": "130010"},
    ])
    cp = orch.checkpoint_path(tmp_path, "VALIDATION_2025", "2025-07-15")
    write_valid_checkpoint(
        cp,
        split="VALIDATION_2025",
        day="2025-07-15",
        codes=["130010"],
        target_sha="target-sha",
        coverage_sha="coverage-sha",
    )
    rows, missing, source_bytes = orch.collect_checkpoints(
        split="VALIDATION_2025",
        outdir=tmp_path,
        targets=targets,
        target_sha256="target-sha",
        coverage_sha256="coverage-sha",
    )
    assert len(rows) == 1
    assert missing == ["2025-07-16"]
    assert source_bytes == 0
