"""F4-1 batch bridge tests with no live acquisition."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from build_f3_research_batch import build_batch as build_f3
from build_f4_observed_origin_batch import build_batch as build_f4
from build_f4_research_motion_batch import build_batch
from test_f4_observed_origin_batch import _make_batch


def _make_f4(root, status="COMPLETE_FEATURES"):
    name = _make_batch(root, status=status)
    build_f4(root)
    return name


def test_batch_no_forecast_and_origin_links(tmp_path):
    name = _make_f4(tmp_path)
    # Fixture has a new parent without matched motion; retain it as unsupported,
    # rather than fabricate a future location or a negative LPZ label.
    bundle_path = tmp_path / "slots" / name
    bundle = json.loads(bundle_path.read_text())
    track = bundle["components"]["radar_tracking"]["tracking"]["30"]
    track["transitions"] = [{
        "from_valid_time": "2026-09-21T03:25:00Z",
        "to_valid_time": "2026-09-21T03:30:00Z",
        "elapsed_seconds": 300, "primary_matches": []}]
    bundle_path.write_text(json.dumps(bundle))
    # F3/F4-0 input hashes belong to the original source, so do not run modified
    # fixture through batch: source immutability is a required contract.
    with pytest.raises(ValueError, match="different source bundle"):
        build_batch(tmp_path)
    assert not (tmp_path / "f4_research_motion").exists()


def test_complete_batch_requires_tracking_transition(tmp_path):
    _make_f4(tmp_path)
    with pytest.raises(ValueError, match="missing radar primary-match transitions"):
        build_batch(tmp_path)
    assert not (tmp_path / "f4_research_motion").exists()


@pytest.mark.parametrize("status", ["COMPLETE_NO_TRACKABLE_EVENT",
                                    "COMPLETE_NO_EMBEDDED_GENESIS",
                                    "TECHNICAL_INCOMPLETE"])
def test_non_feature_status_preserved(tmp_path, status):
    _make_f4(tmp_path, status=status)
    result = build_batch(tmp_path)
    row = result["slot_results"][0]
    assert row["research_status"] == ("SOURCE_INCOMPLETE" if status == "TECHNICAL_INCOMPLETE"
                                      else "NO_DOWNSTREAM_RESEARCH_OBJECT")
    assert row["projected_object_count"] == (None if status == "TECHNICAL_INCOMPLETE" else 0)
    assert result["lpz_forecast_generated"] is False
    assert not (tmp_path / "f4_research_motion" / "slots").exists()


def test_refuses_repeat(tmp_path):
    _make_f4(tmp_path, status="COMPLETE_NO_TRACKABLE_EVENT")
    build_batch(tmp_path)
    with pytest.raises(FileExistsError):
        build_batch(tmp_path)
