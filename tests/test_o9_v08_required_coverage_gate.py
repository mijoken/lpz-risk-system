from __future__ import annotations

from scripts import o9_v08_required_coverage_gate as mod


def granules_for_dates(*groups: list[str]) -> list[dict]:
    dates = []
    for group in groups:
        dates.extend(group)
    starts = mod.required_slot_starts(dates)
    return [
        {
            "start_utc": mod.iso_z(x),
            "short_name": "GPM_3IMERGHH",
            "version": "08",
            "official_final_product": True,
        }
        for x in sorted(starts)
    ]


def test_complete_exact_slots_pass():
    dev = ["2023-01-01", "2023-01-02"]
    val = ["2025-12-31"]
    report = mod.evaluate_coverage(
        development_dates=dev,
        validation_dates=val,
        development_row_count=2,
        validation_row_count=1,
        granules=granules_for_dates(dev, val),
        expected_development_rows=2,
        expected_validation_rows=1,
    )
    assert report["gate"] == mod.PASS_GATE
    assert report["development_missing_slot_count"] == 0
    assert report["validation_missing_slot_count"] == 0
    assert report["all_required_slots_covered"] is True
    assert report["risk_engine_allowed"] is False


def test_one_missing_half_hour_blocks_coverage():
    dev = ["2023-01-01"]
    val = ["2025-01-01"]
    rows = granules_for_dates(dev, val)
    val_required = mod.required_slot_starts(val)
    victim = mod.iso_z(sorted(val_required)[10])
    rows = [r for r in rows if r["start_utc"] != victim]
    report = mod.evaluate_coverage(
        development_dates=dev,
        validation_dates=val,
        development_row_count=1,
        validation_row_count=1,
        granules=rows,
        expected_development_rows=1,
        expected_validation_rows=1,
    )
    assert report["gate"].startswith("WAIT_")
    assert report["validation_missing_slot_count"] == 1
    assert report["all_required_slots_covered"] is False


def test_v07_cannot_satisfy_v08_required_slot():
    dev = ["2023-01-01"]
    val = ["2025-01-01"]
    rows = granules_for_dates(dev, val)
    victim = rows[0]
    victim["version"] = "07"
    report = mod.evaluate_coverage(
        development_dates=dev,
        validation_dates=val,
        development_row_count=1,
        validation_row_count=1,
        granules=rows,
        expected_development_rows=1,
        expected_validation_rows=1,
    )
    assert report["gate"].startswith("WAIT_")
    assert report["wrong_or_nonfinal_metadata_row_count_ignored"] == 1
    assert report["development_missing_slot_count"] + report["validation_missing_slot_count"] >= 1


def test_region_day_counts_are_hard_gates():
    try:
        mod.evaluate_coverage(
            development_dates=["2023-01-01"],
            validation_dates=["2025-01-01"],
            development_row_count=5942,
            validation_row_count=1218,
            granules=[],
        )
    except ValueError as exc:
        assert "5943" in str(exc)
    else:
        raise AssertionError("wrong Development population size was accepted")
