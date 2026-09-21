"""F3-2 batch connection tests. Synthetic inputs; no weather acquisition."""
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "build_f3_research_batch.py"
)

spec = importlib.util.spec_from_file_location("f3_batch", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_root(tmp_path, status="COMPLETE_FEATURES"):
    root = tmp_path / "batch"
    slots = root / "slots"
    slots.mkdir(parents=True)

    (root / "batch_manifest.json").write_text(
        json.dumps({
            "run_id": "synthetic-test",
            "state": "PASS_SELF_HEALING_BATCH",
            "risk_engine_allowed": False,
        }),
        encoding="utf-8",
    )

    bundle = {
        "schema_version": "0.4.0",
        "collection_slot_utc": "2026-09-21T00:00:00Z",
        "prospective_as_of_utc": "2026-09-21T00:15:00Z",
        "archive_role": "PROSPECTIVE_NATIVE",
        "collection_status": status,
        "bundle_complete": status != "TECHNICAL_INCOMPLETE",
        "as_of_time_guard_pass": True,
        "risk_engine_allowed": False,
        "risk_score": None,
        "lpz_classification": None,
    }

    if status == "COMPLETE_FEATURES":
        bundle["components"] = {
            "parent_precursor_features": {
                "execution_ok": True,
                "risk_engine_allowed": False,
                "risk_score": None,
                "classification": None,
                "descriptor_count": 1,
                "descriptors": [{"synthetic_descriptor": 123}],
            }
        }

    (slots / "20260921T000000Z.json").write_text(
        json.dumps(bundle),
        encoding="utf-8",
    )

    return root


def test_complete_features_generate_research_object(tmp_path):
    root = make_root(tmp_path)

    result = module.build_batch(root)

    assert result["source_slot_count"] == 1
    assert result["research_object_count"] == 1
    assert result["forecast_generated"] is False
    assert result["risk_engine_allowed"] is False

    output = (
        root / "f3_research" / "slots"
        / "20260921T000000Z.json"
    )

    payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["research_object_count"] == 1
    assert payload["research_objects"][0]["geometry"] is None
    assert payload["research_objects"][0]["forecast_probability"] is None


@pytest.mark.parametrize("status", [
    "COMPLETE_NO_TRACKABLE_EVENT",
    "COMPLETE_NO_EMBEDDED_GENESIS",
])
def test_no_event_is_not_lpz_negative(tmp_path, status):
    root = make_root(tmp_path, status)

    result = module.build_batch(root)

    assert result["research_object_count"] == 0
    assert result["slot_results"][0]["research_status"] == (
        "NO_DOWNSTREAM_RESEARCH_OBJECT"
    )
    assert result["forecast_generated"] is False


def test_technical_incomplete_is_not_negative(tmp_path):
    root = make_root(tmp_path, "TECHNICAL_INCOMPLETE")

    result = module.build_batch(root)

    assert result["slot_results"][0]["research_status"] == (
        "SOURCE_INCOMPLETE"
    )
    assert result["slot_results"][0]["research_object_count"] is None


def test_asof_guard_rejects_unsafe_features(tmp_path):
    root = make_root(tmp_path)

    path = root / "slots" / "20260921T000000Z.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    payload["as_of_time_guard_pass"] = False

    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        module.build_batch(root)


def test_refuses_overwrite(tmp_path):
    root = make_root(tmp_path)

    module.build_batch(root)

    with pytest.raises(FileExistsError):
        module.build_batch(root)
