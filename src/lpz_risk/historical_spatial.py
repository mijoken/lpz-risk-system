"""Build a compact primary-subdivision geometry registry from official JMA GIS.

Only small derived metadata (bbox/representative center/provenance) are retained.
The large source archive is never committed.
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
            # Force field-name and complete record decoding before accepting.
            _ = [f[0] for f in reader.fields[1:]]
            _ = list(reader.iterRecords())
            return reader, enc
        except Exception as exc:  # pyshp raises dbfFileException, not UnicodeDecodeError.
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


def build_primary_subdivision_registry(zip_bytes: bytes, required_codes: set[str]) -> dict[str, Any]:
    if not zip_bytes:
        raise ValueError("empty JMA GIS archive")

    registry: dict[str, dict[str, Any]] = {}
    inspected_bases: list[str] = []
    matched_fields: list[dict[str, str]] = []
    detected_encodings: list[dict[str, str]] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        bases = sorted({name[:-4] for name in zf.namelist() if name.lower().endswith(".shp")})
        if not bases:
            raise ValueError("archive contains no shapefile")

        for base in bases:
            reader, encoding = _open_reader_with_detected_encoding(zf, base)
            inspected_bases.append(base)
            detected_encodings.append({"shapefile": base, "dbf_encoding": encoding})

            fields = _candidate_code_fields(reader, required_codes)
            if not fields:
                continue
            code_field = fields[0]
            matched_fields.append({"shapefile": base, "code_field": code_field})
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
        "schema_version": "0.1.0",
        "phase": "2B-primary-subdivision-geometry",
        "required_code_count": len(required_codes),
        "resolved_code_count": len(registry),
        "missing_required_codes": missing,
        "inspected_shapefiles": inspected_bases,
        "detected_dbf_encodings": detected_encodings,
        "matched_code_fields": matched_fields,
        "regions": [registry[k] for k in sorted(registry)],
        "geometry_complete_for_required_codes": not missing,
        "risk_engine_allowed": False,
    }
