#!/usr/bin/env python3
"""Phase 2L-O2 — build lightweight public JMA primary-subdivision GeoJSON.

Production purpose:
- derive a browser-friendly map asset for GitHub Pages from official JMA GIS;
- use JMA area.json class10s as the exact nationwide primary-subdivision code set;
- preserve a hard separation between display geometry and scientific geometry.

IMPORTANT:
The simplified/rounded output from this script is DISPLAY ONLY.
It must never be used for rainfall masking, matching, or scientific calculations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_spatial import build_primary_subdivision_geojson  # noqa: E402

DEFAULT_CONFIG = ROOT / "config" / "jma_primary_subdivision_gis.json"
DEFAULT_OUTPUT = ROOT / "web" / "assets" / "japan_primary_subdivisions.geojson"
DEFAULT_REPORT = ROOT / "reports" / "web" / "phase2l_o2_public_geometry_report.json"

USER_AGENT = "lpz-risk-system/0.1 public-map-builder"
EXPECTED_SOURCE_ID = "JMA_PRIMARY_SUBDIVISION_GIS"


def _download(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = resp.read()
    if not payload:
        raise ValueError(f"empty response: {url}")
    return payload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write_json(path: Path, payload: Any, *, compact: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _extract_class10s(area_payload: bytes) -> dict[str, dict[str, Any]]:
    area = json.loads(area_payload.decode("utf-8"))
    class10s = area.get("class10s")
    if not isinstance(class10s, dict) or not class10s:
        raise ValueError("JMA area.json does not contain a non-empty class10s object")

    out: dict[str, dict[str, Any]] = {}
    for raw_code, raw_meta in class10s.items():
        code = str(raw_code).strip()
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"unexpected class10s code: {raw_code!r}")
        if not isinstance(raw_meta, dict):
            raise ValueError(f"class10s metadata is not an object: {code}")
        name = raw_meta.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"class10s missing Japanese name: {code}")
        out[code] = dict(raw_meta)
    return out


def _sqdist(a: list[float], b: list[float]) -> float:
    dx = float(a[0]) - float(b[0])
    dy = float(a[1]) - float(b[1])
    return dx * dx + dy * dy


def _point_segment_sqdist(p: list[float], a: list[float], b: list[float]) -> float:
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    px, py = float(p[0]), float(p[1])
    dx, dy = bx - ax, by - ay
    if dx == 0.0 and dy == 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    qx, qy = ax + t * dx, ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


def _rdp_open(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 2 or tolerance <= 0.0:
        return points[:]
    tol2 = tolerance * tolerance
    a, b = points[0], points[-1]
    max_d2 = -1.0
    index = -1
    for i in range(1, len(points) - 1):
        d2 = _point_segment_sqdist(points[i], a, b)
        if d2 > max_d2:
            max_d2 = d2
            index = i
    if max_d2 > tol2 and index > 0:
        left = _rdp_open(points[: index + 1], tolerance)
        right = _rdp_open(points[index:], tolerance)
        return left[:-1] + right
    return [a, b]


def _dedupe_consecutive(points: Iterable[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for p in points:
        q = [float(p[0]), float(p[1])]
        if not out or q != out[-1]:
            out.append(q)
    return out


def _simplify_ring(coords: list[list[float]], tolerance: float, decimals: int) -> list[list[float]]:
    pts = _dedupe_consecutive(coords)
    if len(pts) < 4:
        return [[round(p[0], decimals), round(p[1], decimals)] for p in pts]

    if pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        original = _dedupe_consecutive(coords)
        return [[round(p[0], decimals), round(p[1], decimals)] for p in original]

    i0 = min(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))
    p0 = pts[i0]
    i1 = max(range(len(pts)), key=lambda i: _sqdist(pts[i], p0))
    if i0 == i1:
        rounded = [[round(p[0], decimals), round(p[1], decimals)] for p in pts]
        rounded.append(rounded[0][:])
        return rounded

    rotated = pts[i0:] + pts[:i0]
    j = (i1 - i0) % len(pts)
    if j <= 0 or j >= len(rotated):
        j = max(range(1, len(rotated)), key=lambda i: _sqdist(rotated[i], rotated[0]))

    chain1 = rotated[: j + 1]
    chain2 = rotated[j:] + [rotated[0]]
    simp1 = _rdp_open(chain1, tolerance)
    simp2 = _rdp_open(chain2, tolerance)
    merged = simp1 + simp2[1:]

    if merged[0] != merged[-1]:
        merged.append(merged[0][:])
    distinct = {tuple(p) for p in merged[:-1]}
    if len(distinct) < 3:
        merged = pts + [pts[0][:]]

    rounded = [[round(p[0], decimals), round(p[1], decimals)] for p in merged]
    rounded = _dedupe_consecutive(rounded)
    if rounded and rounded[0] != rounded[-1]:
        rounded.append(rounded[0][:])
    if len(rounded) < 4:
        fallback = [[round(p[0], decimals), round(p[1], decimals)] for p in pts]
        fallback.append(fallback[0][:])
        return fallback
    return rounded


def _count_vertices_geometry(geometry: dict[str, Any]) -> int:
    gtype = geometry.get("type")
    if gtype == "Polygon":
        return sum(len(ring) for ring in geometry.get("coordinates", []))
    if gtype == "MultiPolygon":
        return sum(len(ring) for polygon in geometry.get("coordinates", []) for ring in polygon)
    if gtype == "GeometryCollection":
        return sum(_count_vertices_geometry(g) for g in geometry.get("geometries", []))
    raise ValueError(f"unsupported geometry type: {gtype!r}")


def _transform_geometry(geometry: dict[str, Any], *, tolerance: float, decimals: int) -> dict[str, Any]:
    gtype = geometry.get("type")
    if gtype == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [_simplify_ring(ring, tolerance, decimals) for ring in geometry.get("coordinates", [])],
        }
    if gtype == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [_simplify_ring(ring, tolerance, decimals) for ring in polygon]
                for polygon in geometry.get("coordinates", [])
            ],
        }
    if gtype == "GeometryCollection":
        return {
            "type": "GeometryCollection",
            "geometries": [
                _transform_geometry(g, tolerance=tolerance, decimals=decimals)
                for g in geometry.get("geometries", [])
            ],
        }
    raise ValueError(f"unsupported geometry type: {gtype!r}")


def _validate_coordinates(geometry: dict[str, Any]) -> None:
    gtype = geometry.get("type")
    if gtype == "Polygon":
        polygons = [geometry.get("coordinates", [])]
    elif gtype == "MultiPolygon":
        polygons = geometry.get("coordinates", [])
    elif gtype == "GeometryCollection":
        for g in geometry.get("geometries", []):
            _validate_coordinates(g)
        return
    else:
        raise ValueError(f"unsupported geometry type: {gtype!r}")

    for polygon in polygons:
        if not polygon:
            raise ValueError("polygon has no rings")
        for ring in polygon:
            if len(ring) < 4:
                raise ValueError("polygon ring has fewer than 4 coordinates")
            if ring[0] != ring[-1]:
                raise ValueError("polygon ring is not closed")
            if len({tuple(p) for p in ring[:-1]}) < 3:
                raise ValueError("polygon ring has fewer than 3 distinct vertices")
            for lon, lat in ring:
                if not (118.0 <= float(lon) <= 156.0 and 18.0 <= float(lat) <= 50.0):
                    raise ValueError(f"coordinate outside expected Japan GIS envelope: {(lon, lat)}")


def _public_feature(
    feature: dict[str, Any],
    meta: dict[str, Any],
    *,
    tolerance: float,
    decimals: int,
) -> tuple[dict[str, Any], int, int]:
    code = str(feature["id"])
    raw_geometry = feature["geometry"]
    before = _count_vertices_geometry(raw_geometry)
    geometry = _transform_geometry(raw_geometry, tolerance=tolerance, decimals=decimals)
    _validate_coordinates(geometry)
    after = _count_vertices_geometry(geometry)

    props = feature.get("properties", {})
    public = {
        "type": "Feature",
        "id": code,
        "properties": {
            "region_code": code,
            "geometry_key": code,
            "name_ja": meta.get("name"),
            "name_en": meta.get("enName"),
            "parent_code": meta.get("parent"),
            "office_name_ja": meta.get("officeName"),
            "source_part_count": props.get("source_part_count"),
        },
        "geometry": geometry,
    }
    return public, before, after


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    ap.add_argument(
        "--tolerance-deg",
        type=float,
        default=0.0015,
        help="Display-only RDP tolerance in degrees. Never used for science.",
    )
    ap.add_argument(
        "--coordinate-decimals",
        type=int,
        default=5,
        help="Decimal places retained in display-only GeoJSON.",
    )
    ap.add_argument(
        "--max-output-mib",
        type=float,
        default=10.0,
        help="Fail if final public GeoJSON is larger than this.",
    )
    args = ap.parse_args()

    if args.tolerance_deg < 0:
        raise ValueError("--tolerance-deg must be >= 0")
    if not (4 <= args.coordinate_decimals <= 8):
        raise ValueError("--coordinate-decimals must be between 4 and 8")
    if args.max_output_mib <= 0:
        raise ValueError("--max-output-mib must be > 0")

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if cfg.get("source_id") != EXPECTED_SOURCE_ID:
        raise ValueError(f"unexpected source_id: {cfg.get('source_id')!r}")

    print("=" * 104)
    print("LPZ PHASE 2L-O2 — PUBLIC JMA PRIMARY-SUBDIVISION GEOJSON")
    print("=" * 104)
    print("Downloading JMA area metadata ...")
    area_bytes = _download(str(cfg["area_metadata_url"]))
    class10s = _extract_class10s(area_bytes)
    required_codes = set(class10s)
    print(f"JMA class10s regions             : {len(required_codes)}")

    print("Downloading official JMA primary-subdivision GIS archive ...")
    zip_bytes = _download(str(cfg["zip_url"]))
    print(f"GIS archive downloaded           : {len(zip_bytes) / (1024**2):.1f} MiB")

    official = build_primary_subdivision_geojson(zip_bytes, required_codes)
    missing = list(official.get("missing_required_codes") or [])
    if missing:
        raise RuntimeError(
            f"official JMA geometry missing {len(missing)} class10s codes: {missing[:20]}"
        )
    if int(official.get("resolved_code_count", -1)) != len(required_codes):
        raise RuntimeError("resolved official geometry count does not equal JMA class10s count")

    public_features: list[dict[str, Any]] = []
    before_vertices = 0
    after_vertices = 0
    seen: set[str] = set()

    for feature in official["features"]:
        code = str(feature["id"])
        if code not in class10s:
            raise RuntimeError(f"official geometry produced non-class10s code: {code}")
        if code in seen:
            raise RuntimeError(f"duplicate public geometry feature code: {code}")
        seen.add(code)
        pub, before, after = _public_feature(
            feature,
            class10s[code],
            tolerance=args.tolerance_deg,
            decimals=args.coordinate_decimals,
        )
        public_features.append(pub)
        before_vertices += before
        after_vertices += after

    if seen != required_codes:
        missing_final = sorted(required_codes - seen)
        extra_final = sorted(seen - required_codes)
        raise RuntimeError(f"public feature code mismatch: missing={missing_final}, extra={extra_final}")

    public_features.sort(key=lambda f: str(f["id"]))
    output_obj = {
        "type": "FeatureCollection",
        "schema_version": "1.0.0",
        "product": "LPZ_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOMETRY",
        "geographic_unit": "JMA_PRIMARY_SUBDIVISION",
        "geometry_key": "region_code",
        "display_geometry_semantics": "SIMPLIFIED_DERIVATIVE_FOR_WEB_DISPLAY_ONLY",
        "scientific_masking_allowed": False,
        "risk_engine_allowed": False,
        "source": {
            "authority": cfg["source_authority"],
            "source_id": cfg["source_id"],
            "source_page": cfg["source_page"],
            "source_zip_url": cfg["zip_url"],
            "area_metadata_url": cfg["area_metadata_url"],
            "source_crs": "JGD2011 geographic lon/lat",
            "source_zip_sha256": _sha256(zip_bytes),
            "area_metadata_sha256": _sha256(area_bytes),
        },
        "display_transform": {
            "simplification_algorithm": "RDP_CLOSED_RING_TWO_CHAIN",
            "tolerance_degrees": args.tolerance_deg,
            "coordinate_decimals": args.coordinate_decimals,
            "research_geometry_modified": False,
        },
        "region_count": len(public_features),
        "features": public_features,
    }

    _atomic_write_json(args.output, output_obj, compact=True)
    size_bytes = args.output.stat().st_size
    size_mib = size_bytes / (1024**2)
    if size_mib > args.max_output_mib:
        args.output.unlink(missing_ok=True)
        raise RuntimeError(
            f"public GeoJSON would be {size_mib:.2f} MiB, above "
            f"--max-output-mib={args.max_output_mib:.2f}; increase simplification carefully"
        )

    ratio = (after_vertices / before_vertices) if before_vertices else 0.0
    report = {
        "schema_version": "1.0.0",
        "phase": "2L-O2-public-primary-subdivision-geometry",
        "gate": "PASS_PHASE2L_O2_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOJSON",
        "source_id": cfg["source_id"],
        "jma_class10s_count": len(required_codes),
        "official_geometry_resolved_count": len(seen),
        "missing_codes": [],
        "output": str(args.output),
        "output_size_bytes": size_bytes,
        "output_size_mib": size_mib,
        "official_vertex_count_before_display_transform": before_vertices,
        "public_vertex_count_after_display_transform": after_vertices,
        "vertex_retention_fraction": ratio,
        "tolerance_degrees": args.tolerance_deg,
        "coordinate_decimals": args.coordinate_decimals,
        "scientific_masking_allowed": False,
        "research_geometry_modified": False,
        "risk_engine_allowed": False,
        "source_zip_sha256": _sha256(zip_bytes),
        "area_metadata_sha256": _sha256(area_bytes),
    }
    _atomic_write_json(args.report, report, compact=False)

    print(f"Official geometry resolved       : {len(seen)} / {len(required_codes)}")
    print(f"Vertices before display simplify : {before_vertices:,}")
    print(f"Vertices after display simplify  : {after_vertices:,}")
    print(f"Vertex retention                 : {ratio:.2%}")
    print(f"Public GeoJSON size              : {size_mib:.2f} MiB")
    print("Scientific masking allowed       : NO")
    print("Research geometry modified       : NO")
    print("Risk engine                      : NOT ALLOWED")
    print("")
    print("Gate                             : PASS_PHASE2L_O2_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOJSON")
    print(f"GeoJSON                          : {args.output}")
    print(f"Report                           : {args.report}")
    print("=" * 104)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
