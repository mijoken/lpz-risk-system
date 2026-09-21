"""F4 map-first research export contracts."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_f4_archived_geographic_research import coords, build


def test_geographic_coordinate_order():
    assert coords({"lon": 139.65, "lat": 35.45}) == [139.65, 35.45]


@pytest.mark.parametrize("point", [
    {"lon": 181, "lat": 35}, {"lon": 139, "lat": -91},
    {"lon": float("nan"), "lat": 35},
])
def test_invalid_geographic_coordinates_refused(point):
    with pytest.raises(ValueError):
        coords(point)


def test_no_unverified_or_missing_archived_source(tmp_path):
    (tmp_path / "f3_research").mkdir()
    (tmp_path / "batch_manifest.json").write_text(
        '{"run_id":"35564667965","risk_engine_allowed":false}', encoding="utf-8")
    (tmp_path / "f3_research" / "manifest.json").write_text(
        '{"source_run_id":"35564667965","risk_engine_allowed":true,"forecast_generated":false}',
        encoding="utf-8")
    with pytest.raises(ValueError, match="provenance/release"):
        build(tmp_path)
