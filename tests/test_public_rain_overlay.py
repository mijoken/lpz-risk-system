from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_public_rain_overlay.py"

spec = importlib.util.spec_from_file_location("public_rain_overlay", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_select_frames_respects_settled_lag_and_spacing():
    rows = []
    for minute in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
        stamp = f"2026091212{minute:02d}00"
        rows.append(
            {
                "basetime": stamp,
                "validtime": stamp,
                "elements": ["hrpns"],
            }
        )

    selected = module.select_frames(
        rows,
        now=datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc),
        settled_lag_minutes=15,
        frame_count=3,
        frame_spacing_minutes=15,
    )
    assert [row["validtime"] for row in selected] == [
        "20260912121500",
        "20260912123000",
        "20260912124500",
    ]


def test_public_view_uses_exact_49_z6_tiles():
    x0, x1, y0, y1 = module.tile_bounds(module.ZOOM)
    assert (x1 - x0 + 1) * (y1 - y0 + 1) == 49


def test_legend_preserves_official_interval_classes():
    legend = module.legend()
    assert len(legend) == 8
    assert legend[0]["lower_mmph"] == 0.0
    assert legend[-1]["lower_mmph"] == 80.0
    assert legend[-1]["upper_mmph"] is None
