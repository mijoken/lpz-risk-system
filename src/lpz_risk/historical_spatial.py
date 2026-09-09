"""Build compact primary-subdivision geometry from official JMA GIS.

The large official archive is never committed. Two derived products are
supported:

- bbox registry for ERA5 request subsetting;
- GeoJSON FeatureCollection for exact primary-subdivision polygon masking of
  historical rainfall grids.
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import shapefile

_CODE_RE = re.compile(r"^\d{6}$")


def _merge_bbox(a: list[float] | None, b: list[float]) -> list[float]:
    if a is None:
        return list(map(float, b))
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _validate_lonlat_bbox(bbox: list[float]) -> None:
    xmin, ymin, xmax, ymax = bbox
    if xmin > xmax or ymin > ymax:
        raise ValueError(f"invalid bbox ordering: {bbox}")
    if not (118.0 <= xmin <= 156.0 and 118.0 <= xmax <= 156.0 and 18.0 <= ymin <= 50.0 and 18.0 <= ymax <= 50.0):
        raise ValueError(f"bbox does not look like geographic JGD2011 lon/lat degrees: {bbox}")


def _reader_from_members(zf: zipfile.ZipFile, base: str, encoding: str) -> shapefile.Reader:
    names = set(zf.namelist())
    shp_name, shx_name, dbf_name = base + ".shp", base + ".shx", base + ".dbf"
    if shp_name not in names or dbf_name not in names:
        raise ValueError(f"incomplete shapefile set for {base}")
    kwargs: dict[str, Any] = {
        "shp": io.BytesIO(zf.read(shp_name)),
        "dbf": io.BytesIO(zf.read(dbf_name)),
        "encoding": encoding,
    }
    if shx_name in names:
        kwargs["shx"] = io.BytesIO(zf.read(shx_name))
    return shapefile.Reader(**kwargs)


def _open_reader_with_detected_encoding(zf: zipfile.ZipFile, base: str) -> tuple[shapefile.Reader, str]:
    last_error: Exception | None = None
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis"):
        try:
            reader = _reader_from_members(zf, base, enc)
            _ = [f[0] for f in reader.fields[1:]]
            _ = list(reader.iterRecords())
            return reader, enc
        except Exception as exc:
            last_error = exc
    raise ValueError(f"could not decode DBF for {base}: {type(last_error).__name__}: {last_error}")


def _candidate_code_fields(reader: shapefile.Reader, required_codes: set[str]) -> list[str]:
    field_names = [f[0] for f in reader.fields[1:]]
    matches: list[tuple[int, str]] = []
    records = list(reader.iterRecords())
    for idx, name in enumerate(field_names):
        values = {str(r[idx]).strip() for r in records}
        six = {v for v in values if _CODE_RE.fullmatch(v)}
        overlap = len(six & required_codes) if required_codes else len(six)
        if six and overlap:
            matches.append((overlap, name))
    matches.sort(reverse=True)
    return [name for _, name in matches]


def _iter_matching_shape_records(zip_bytes: bytes, required_codes: set[str]):
    """Yield (code, shape, base, encoding, code_field) from the official archive."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        bases = sorted({name[:-4] for name in zf.namelist() if name.lower().endswith(".shp")})
        if not bases:
            raise ValueError("archive contains no shapefile")
        for base in bases:
            reader, encoding = _open_reader_with_detected_encoding(zf, base)
            fields = _candidate_code_fields(reader, required_codes)
            if not fields:
                continue
            code_field = fields[0]
            field_names = [f[0] for f in reader.fields[1:]]
            code_idx = field_names.index(code_field)
            for sr in reader.iterShapeRecords():
                code = str(sr.record[code_idx]).strip()
                if not _CODE_RE.fullmatch(code):
                    continue
                if required_codes and code not in required_codes:
                    continue
                bbox = list(map(float, sr.shape.bbox))
                _validate_lonlat_bbox(bbox)
                yield code, sr.shape, base, encoding, code_field


def build_primary_subdivision_registry(zip_bytes: bytes, required_codes: set[str]) -> dict[str, Any]:
    if not zip_bytes:
        raise ValueError("empty JMA GIS archive")

    registry: dict[str, dict[str, Any]] = {}
    inspected: set[str] = set()
    encoding_by_base: dict[str, str] = {}
    field_by_base: dict[str, str] = {}

    for code, shape, base, encoding, code_field in _iter_matching_shape_records(zip_bytes, required_codes):
        inspected.add(base)
        encoding_by_base[base] = encoding
        field_by_base[base] = code_field
        bbox = list(map(float, shape.bbox))
        entry = registry.setdefault(code, {"primary_subdivision_code": code, "bbox": None, "source_parts": 0})
        entry["bbox"] = _merge_bbox(entry["bbox"], bbox)
        entry["source_parts"] += 1

    for entry in registry.values():
        xmin, ymin, xmax, ymax = entry["bbox"]
        entry["bbox"] = [xmin, ymin, xmax, ymax]
        entry["bbox_center_lon"] = (xmin + xmax) / 2.0
        entry["bbox_center_lat"] = (ymin + ymax) / 2.0
        entry["representative_point_semantics"] = "BBOX_CENTER_NOT_POLYGON_CENTROID"

    missing = sorted(required_codes - set(registry))
    return {
        "schema_version": "0.2.0",
        "phase": "2B-primary-subdivision-geometry",
        "required_code_count": len(required_codes),
        "resolved_code_count": len(registry),
        "missing_required_codes": missing,
        "inspected_shapefiles": sorted(inspected),
        "detected_dbf_encodings": [{"shapefile": b, "dbf_encoding": encoding_by_base[b]} for b in sorted(encoding_by_base)],
        "matched_code_fields": [{"shapefile": b, "code_field": field_by_base[b]} for b in sorted(field_by_base)],
        "regions": [registry[k] for k in sorted(registry)],
        "geometry_complete_for_required_codes": not missing,
        "risk_engine_allowed": False,
    }


def build_primary_subdivision_geojson(zip_bytes: bytes, required_codes: set[str]) -> dict[str, Any]:
    """Derive a compact GeoJSON FeatureCollection for only required codes.

    Multiple official shape records for one code are preserved as a
    GeometryCollection rather than dissolved. This avoids topology-changing
    approximations and naturally retains islands/multipart geometries. The
    source coordinate system is JGD2011 geographic lon/lat as documented by JMA.
    """
    if not zip_bytes:
        raise ValueError("empty JMA GIS archive")

    geometries: dict[str, list[dict[str, Any]]] = {}
    provenance: dict[str, list[dict[str, str]]] = {}
    for code, shape, base, encoding, code_field in _iter_matching_shape_records(zip_bytes, required_codes):
        geo = shape.__geo_interface__
        if geo.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"unexpected primary-subdivision geometry type for {code}: {geo.get('type')}")
        geometries.setdefault(code, []).append(geo)
        provenance.setdefault(code, []).append({
            "shapefile": base,
            "dbf_encoding": encoding,
            "code_field": code_field,
        })

    missing = sorted(required_codes - set(geometries))
    features: list[dict[str, Any]] = []
    for code in sorted(geometries):
        parts = geometries[code]
        geometry = parts[0] if len(parts) == 1 else {"type": "GeometryCollection", "geometries": parts}
        features.append({
            "type": "Feature",
            "id": code,
            "properties": {
                "primary_subdivision_code": code,
                "source_part_count": len(parts),
                "source_authority": "Japan Meteorological Agency",
                "source_crs": "JGD2011 geographic lon/lat",
                "provenance": provenance[code],
                "mask_semantics": "GRID_CELL_CENTRE_INSIDE_OFFICIAL_POLYGON",
            },
            "geometry": geometry,
        })

    return {
        "type": "FeatureCollection",
        "schema_version": "0.1.0",
        "phase": "2C-primary-subdivision-polygon-geometry",
        "required_code_count": len(required_codes),
        "resolved_code_count": len(features),
        "missing_required_codes": missing,
        "geometry_complete_for_required_codes": not missing,
        "features": features,
        "risk_engine_allowed": False,
    }
