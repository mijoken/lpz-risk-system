from __future__ import annotations

import io
import unittest
import zipfile

import shapefile

from lpz_risk.historical_spatial import build_primary_subdivision_registry


def _synthetic_zip() -> bytes:
    shp = io.BytesIO()
    shx = io.BytesIO()
    dbf = io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="cp932")
    w.field("AREA_CODE", "C", size=6)
    w.field("NAME", "C", size=40)
    ring = [[130.0, 32.0], [131.0, 32.0], [131.0, 33.0], [130.0, 33.0], [130.0, 32.0]]
    w.poly([ring])
    w.record("400000", "TEST")
    w.close()

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("area/test.shp", shp.getvalue())
        zf.writestr("area/test.shx", shx.getvalue())
        zf.writestr("area/test.dbf", dbf.getvalue())
    return out.getvalue()


class HistoricalSpatialTest(unittest.TestCase):
    def test_extracts_required_code_bbox(self):
        report = build_primary_subdivision_registry(_synthetic_zip(), {"400000"})
        self.assertTrue(report["geometry_complete_for_required_codes"])
        self.assertEqual(report["resolved_code_count"], 1)
        region = report["regions"][0]
        self.assertEqual(region["primary_subdivision_code"], "400000")
        self.assertEqual(region["bbox"], [130.0, 32.0, 131.0, 33.0])
        self.assertEqual(region["representative_point_semantics"], "BBOX_CENTER_NOT_POLYGON_CENTROID")

    def test_missing_code_is_explicit(self):
        report = build_primary_subdivision_registry(_synthetic_zip(), {"999999"})
        self.assertFalse(report["geometry_complete_for_required_codes"])
        self.assertEqual(report["missing_required_codes"], ["999999"])


if __name__ == "__main__":
    unittest.main()
