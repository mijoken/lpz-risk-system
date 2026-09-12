#!/usr/bin/env python3
"""Build topology-safe display-only JMA primary-subdivision map LOD products.

This builder exists because the original O2 web simplifier retained collapsed
small rings as three-vertex triangles. That policy kept every source island but
created visually misleading long triangular edges at high zoom. The products
built here are display-only and never feed scientific masking or LPZ logic.

Policy:
- derive from the official JMA primary-subdivision GIS archive;
- keep all 142 primary-subdivision codes;
- prune tiny *polygon parts* by LOD instead of fabricating triangle floors;
- adaptively reduce simplification tolerance when a retained ring would collapse;
- preserve the largest official polygon part for a region even when it is below
  the LOD pruning threshold;
- keep scientific/risk release flags locked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

DEFAULT_CONFIG = ROOT / "config" / "jma_primary_subdivision_gis.json"
DEFAULT_ASSET_DIR = ROOT / "web" / "assets" / "map"
DEFAULT_COMPAT_OUTPUT = ROOT / "web" / "assets" / "japan_primary_subdivisions.geojson"
DEFAULT_REPORT = ROOT / "reports" / "web" / "phase2l_o7_public_map_lod_report.json"

PASS_GATE = "PASS_PHASE2L_O7_TOPOLOGY_SAFE_PUBLIC_MAP_LOD"
MAX_DECIMALS = 8


@dataclass(frozen=True)
class LodSpec:
    lod_id: str
    path_name: str
    min_scale: float
    max_scale: float | None
    tolerance_degrees: float
    min_polygon_area_deg2: float
    min_hole_area_deg2: float
    decimals: int


LOD_SPECS = (
    LodSpec(
        lod_id="overview",
        path_name="jma_primary_overview.geojson",
        min_scale=1.0,
        max_scale=1.85,
        tolerance_degrees=0.024,
        min_polygon_area_deg2=0.0010,
        min_hole_area_deg2=0.0030,
        decimals=5,
    ),
    LodSpec(
        lod_id="regional",
        path_name="jma_primary_regional.geojson",
        min_scale=1.85,
        max_scale=3.8,
        tolerance_degrees=0.006,
        min_polygon_area_deg2=0.00015,
        min_hole_area_deg2=0.00060,
        decimals=5,
    ),
    LodSpec(
        lod_id="local",
        path_name="jma_primary_local.geojson",
        min_scale=3.8,
        max_scale=None,
        tolerance_degrees=0.0015,
        min_polygon_area_deg2=0.00002,
        min_hole_area_deg2=0.00008,
        decimals=6,
    ),
)


def download(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "lpz-risk-system/0.1 public-map-lod-builder"},
    )
    with urllib.request.urlopen(req, timeout=240) as response:
        payload = response.read()
    if not payload:
        raise ValueError(f"empty response: {url}")
    return payload


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def dump_bytes(obj: Any) -> bytes:
    return (
        json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


def load_area_metadata(payload: bytes) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    obj = json.loads(payload.decode("utf-8"))
    class10s = obj.get("class10s")
    if not isinstance(class10s, dict) or not class10s:
        raise ValueError("JMA area.json missing class10s")

    lookup: dict[str, dict[str, Any]] = {}
    for family in ("centers", "offices", "class10s", "class15s", "class20s"):
        rows = obj.get(family)
        if isinstance(rows, dict):
            for code, meta in rows.items():
                if isinstance(meta, dict):
                    lookup[str(code)] = meta

    out: dict[str, dict[str, Any]] = {}
    for raw_code, meta in class10s.items():
        code = str(raw_code)
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"bad class10s code: {code}")
        if not isinstance(meta, dict) or not str(meta.get("name", "")).strip():
            raise ValueError(f"bad class10s metadata: {code}")
        out[code] = meta
    return out, lookup


def open_ring(coords: Iterable[Iterable[float]]) -> list[list[float]]:
    points: list[list[float]] = []
    for p in coords:
        q = [float(p[0]), float(p[1])]
        if not points or q != points[-1]:
            points.append(q)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def ring_area_deg2(coords: Iterable[Iterable[float]]) -> float:
    pts = open_ring(coords)
    if len(pts) < 3:
        return 0.0
    area2 = 0.0
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        area2 += a[0] * b[1] - b[0] * a[1]
    return abs(area2) * 0.5


def point_segment_d2(p: list[float], a: list[float], b: list[float]) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    qx = ax + t * dx
    qy = ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


def rdp(points: list[list[float]], tolerance: float) -> list[list[float]]:
    if len(points) <= 2:
        return points[:]
    a = points[0]
    b = points[-1]
    best = -1.0
    index = -1
    for i in range(1, len(points) - 1):
        d2 = point_segment_d2(points[i], a, b)
        if d2 > best:
            best = d2
            index = i
    if best > tolerance * tolerance and index > 0:
        left = rdp(points[: index + 1], tolerance)
        right = rdp(points[index:], tolerance)
        return left[:-1] + right
    return [a, b]


def simplify_closed_ring(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """RDP a cyclic ring without inventing vertices or triangle floors."""
    if len(points) <= 3:
        return points[:]

    i0 = min(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    p0 = points[i0]
    i1 = max(
        range(len(points)),
        key=lambda i: (points[i][0] - p0[0]) ** 2 + (points[i][1] - p0[1]) ** 2,
    )
    rotated = points[i0:] + points[:i0]
    j = (i1 - i0) % len(points)
    if not (0 < j < len(rotated)):
        j = len(rotated) // 2

    merged = rdp(rotated[: j + 1], tolerance) + rdp(rotated[j:] + [rotated[0]], tolerance)[1:]
    deduped: list[list[float]] = []
    for p in merged:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    if deduped and deduped[0] == deduped[-1]:
        deduped.pop()
    return deduped


def close_round(points: list[list[float]], decimals: int) -> list[list[float]]:
    out: list[list[float]] = []
    for p in points:
        q = [round(float(p[0]), decimals), round(float(p[1]), decimals)]
        if not out or q != out[-1]:
            out.append(q)
    if out and out[0] != out[-1]:
        out.append(out[0][:])
    return out


def valid_ring(ring: list[list[float]]) -> bool:
    return (
        len(ring) >= 4
        and ring[0] == ring[-1]
        and len({tuple(p) for p in ring[:-1]}) >= 3
        and all(118.0 <= p[0] <= 156.0 and 18.0 <= p[1] <= 50.0 for p in ring)
    )


def simplify_ring(coords: list[list[float]], tolerance: float, decimals: int, stats: dict[str, int]) -> list[list[float]]:
    points = open_ring(coords)
    if len({tuple(p) for p in points}) < 3:
        raise ValueError("official ring has fewer than three distinct vertices")

    stats["rings_retained"] += 1
    # If a retained ring would collapse, back off the tolerance. We never create
    # a three-vertex surrogate from distant source points merely to keep a ring.
    for attempt in range(9):
        tol = tolerance / (2**attempt)
        simplified = simplify_closed_ring(points, tol)
        if len({tuple(p) for p in simplified}) < 3:
            continue
        for d in range(decimals, MAX_DECIMALS + 1):
            candidate = close_round(simplified, d)
            if valid_ring(candidate):
                if len(candidate) - 1 < len(points):
                    stats["rings_simplified"] += 1
                if attempt:
                    stats["adaptive_tolerance_backoffs"] += 1
                if d > decimals:
                    stats["precision_escalations"] += 1
                stats["max_decimals_used"] = max(stats["max_decimals_used"], d)
                return candidate

    # Last-resort display fallback keeps the original official ring shape,
    # rounded only. This may cost bytes, but cannot invent long triangle edges.
    stats["full_ring_fallbacks"] += 1
    for d in range(decimals, MAX_DECIMALS + 1):
        candidate = close_round(points, d)
        if valid_ring(candidate):
            stats["max_decimals_used"] = max(stats["max_decimals_used"], d)
            return candidate
    raise ValueError("retained official ring could not be represented safely")


def iter_polygons(geometry: dict[str, Any]) -> Iterable[list[list[list[float]]]]:
    kind = geometry.get("type")
    if kind == "Polygon":
        yield geometry.get("coordinates", [])
        return
    if kind == "MultiPolygon":
        for polygon in geometry.get("coordinates", []):
            yield polygon
        return
    if kind == "GeometryCollection":
        for child in geometry.get("geometries", []):
            yield from iter_polygons(child)
        return
    raise ValueError(f"unsupported source geometry type: {kind}")


def geometry_bbox(polygons: list[list[list[list[float]]]]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for polygon in polygons:
        for ring in polygon:
            for lon, lat in ring:
                xs.append(float(lon))
                ys.append(float(lat))
    if not xs:
        raise ValueError("geometry contains no coordinates")
    return min(xs), min(ys), max(xs), max(ys)


def transform_geometry(geometry: dict[str, Any], spec: LodSpec, stats: dict[str, int]) -> dict[str, Any]:
    source_polygons = list(iter_polygons(geometry))
    if not source_polygons:
        raise ValueError("feature has no source polygons")

    ranked = sorted(
        ((ring_area_deg2(polygon[0]) if polygon else 0.0, polygon) for polygon in source_polygons),
        key=lambda row: row[0],
        reverse=True,
    )
    selected = [(area, polygon) for area, polygon in ranked if area >= spec.min_polygon_area_deg2]
    if not selected:
        # Preserve one official part so every JMA primary subdivision remains visible.
        selected = [ranked[0]]
        stats["features_forced_largest_part"] += 1

    stats["polygon_parts_source"] += len(source_polygons)
    stats["polygon_parts_pruned"] += len(source_polygons) - len(selected)

    out_polygons: list[list[list[list[float]]]] = []
    for _, polygon in selected:
        if not polygon:
            continue
        outer = simplify_ring(polygon[0], spec.tolerance_degrees, spec.decimals, stats)
        rings = [outer]
        for hole in polygon[1:]:
            if ring_area_deg2(hole) < spec.min_hole_area_deg2:
                stats["holes_pruned"] += 1
                continue
            rings.append(simplify_ring(hole, spec.tolerance_degrees, spec.decimals, stats))
        out_polygons.append(rings)

    if not out_polygons:
        raise ValueError("all display polygon parts disappeared")
    if len(out_polygons) == 1:
        return {"type": "Polygon", "coordinates": out_polygons[0]}
    return {"type": "MultiPolygon", "coordinates": out_polygons}


def count_vertices(geometry: dict[str, Any]) -> int:
    kind = geometry.get("type")
    if kind == "Polygon":
        return sum(len(r) for r in geometry.get("coordinates", []))
    if kind == "MultiPolygon":
        return sum(len(r) for polygon in geometry.get("coordinates", []) for r in polygon)
    raise ValueError(kind)


def parent_name(meta: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> str | None:
    parent = str(meta.get("parent") or "")
    if not parent:
        return None
    row = lookup.get(parent)
    if not isinstance(row, dict):
        return None
    value = str(row.get("name") or "").strip()
    return value or None


def build_lod(
    official: dict[str, Any],
    class10s: dict[str, dict[str, Any]],
    lookup: dict[str, dict[str, Any]],
    config: dict[str, Any],
    spec: LodSpec,
    *,
    zip_sha: str,
    area_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stats: dict[str, int] = {
        "polygon_parts_source": 0,
        "polygon_parts_pruned": 0,
        "holes_pruned": 0,
        "features_forced_largest_part": 0,
        "rings_retained": 0,
        "rings_simplified": 0,
        "adaptive_tolerance_backoffs": 0,
        "precision_escalations": 0,
        "full_ring_fallbacks": 0,
        "max_decimals_used": spec.decimals,
    }

    features: list[dict[str, Any]] = []
    source_vertices = 0
    display_vertices = 0
    seen: set[str] = set()

    for feature in official.get("features", []):
        code = str(feature.get("id") or "")
        if code not in class10s or code in seen:
            raise RuntimeError(f"bad/duplicate primary-subdivision code: {code}")
        seen.add(code)
        raw_geometry = feature["geometry"]
        raw_polygons = list(iter_polygons(raw_geometry))
        bbox = geometry_bbox(raw_polygons)
        display_geometry = transform_geometry(raw_geometry, spec, stats)
        source_vertices += sum(len(r) for p in raw_polygons for r in p)
        display_vertices += count_vertices(display_geometry)

        meta = class10s[code]
        child_name = str(meta.get("name") or "").strip()
        p_name = parent_name(meta, lookup)
        display_name = f"{p_name} {child_name}".strip() if p_name else child_name
        features.append(
            {
                "type": "Feature",
                "id": code,
                "properties": {
                    "region_code": code,
                    "geometry_key": code,
                    "name_ja": child_name,
                    "name_en": meta.get("enName"),
                    "parent_code": meta.get("parent"),
                    "parent_name_ja": p_name,
                    "display_name_ja": display_name,
                    "office_name_ja": meta.get("officeName"),
                    "label_lon": (bbox[0] + bbox[2]) / 2.0,
                    "label_lat": (bbox[1] + bbox[3]) / 2.0,
                    "label_point_semantics": "OFFICIAL_SOURCE_BBOX_CENTER_DISPLAY_ONLY",
                },
                "geometry": display_geometry,
            }
        )

    if seen != set(class10s):
        missing = sorted(set(class10s) - seen)
        raise RuntimeError(f"public feature code mismatch; missing={missing[:10]}")

    features.sort(key=lambda row: row["id"])
    product = {
        "type": "FeatureCollection",
        "schema_version": "2.0.0",
        "product": "LPZ_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOMETRY",
        "geographic_unit": "JMA_PRIMARY_SUBDIVISION",
        "geometry_key": "region_code",
        "lod": spec.lod_id,
        "display_geometry_semantics": "TOPOLOGY_SAFE_SIMPLIFIED_DERIVATIVE_FOR_WEB_DISPLAY_ONLY",
        "scientific_masking_allowed": False,
        "risk_engine_allowed": False,
        "source": {
            "authority": config["source_authority"],
            "source_id": config["source_id"],
            "source_page": config["source_page"],
            "source_zip_url": config["zip_url"],
            "area_metadata_url": config["area_metadata_url"],
            "source_crs": "JGD2011 geographic lon/lat",
            "source_zip_sha256": zip_sha,
            "area_metadata_sha256": area_sha,
        },
        "display_transform": {
            "simplification_algorithm": "CYCLIC_RDP_WITH_ADAPTIVE_TOLERANCE_BACKOFF",
            "tolerance_degrees": spec.tolerance_degrees,
            "min_polygon_area_deg2": spec.min_polygon_area_deg2,
            "min_hole_area_deg2": spec.min_hole_area_deg2,
            "collapsed_ring_policy": "BACK_OFF_TOLERANCE_THEN_KEEP_OFFICIAL_RING_NEVER_TRIANGLE_FLOOR",
            "tiny_part_policy": "PRUNE_BY_LOD_KEEP_LARGEST_PART_PER_REGION",
            "research_geometry_modified": False,
        },
        "region_count": len(features),
        "features": features,
    }
    report = {
        "lod": spec.lod_id,
        "region_count": len(features),
        "source_vertices": source_vertices,
        "display_vertices": display_vertices,
        "vertex_retention_fraction": display_vertices / source_vertices if source_vertices else None,
        "stats": stats,
    }
    return product, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--asset-dir", default=str(DEFAULT_ASSET_DIR))
    parser.add_argument("--compat-output", default=str(DEFAULT_COMPAT_OUTPUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    area_payload = download(str(config["area_metadata_url"]))
    class10s, lookup = load_area_metadata(area_payload)
    zip_payload = download(str(config["zip_url"]))
    zip_sha = sha256(zip_payload)
    area_sha = sha256(area_payload)

    official = build_primary_subdivision_geojson(zip_payload, set(class10s))
    if not official.get("geometry_complete_for_required_codes"):
        raise RuntimeError(f"official geometry incomplete: {official.get('missing_required_codes')}")
    if len(official.get("features", [])) != 142 or len(class10s) != 142:
        raise RuntimeError(
            f"unexpected JMA class10s count: official={len(official.get('features', []))} metadata={len(class10s)}"
        )

    asset_dir = Path(args.asset_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    lod_reports: list[dict[str, Any]] = []
    lod_manifest: list[dict[str, Any]] = []
    overview_payload: bytes | None = None

    for spec in LOD_SPECS:
        obj, report = build_lod(
            official,
            class10s,
            lookup,
            config,
            spec,
            zip_sha=zip_sha,
            area_sha=area_sha,
        )
        payload = dump_bytes(obj)
        report["bytes"] = len(payload)
        report["mib"] = len(payload) / (1024 * 1024)
        lod_reports.append(report)
        path = asset_dir / spec.path_name
        atomic_write(path, payload)
        if spec.lod_id == "overview":
            overview_payload = payload
        lod_manifest.append(
            {
                "id": spec.lod_id,
                "path": f"assets/map/{spec.path_name}",
                "min_scale": spec.min_scale,
                "max_scale": spec.max_scale,
                "region_count": 142,
                "bytes": len(payload),
            }
        )

    if overview_payload is None:
        raise RuntimeError("overview LOD was not built")
    atomic_write(Path(args.compat_output), overview_payload)

    manifest = {
        "schema_version": "1.0.0",
        "product": "LPZ_PUBLIC_MAP_GEOMETRY_MANIFEST",
        "region_count": 142,
        "default_lod": "overview",
        "lods": lod_manifest,
        "reference_cities_path": "data/reference_cities.json",
        "scientific_masking_allowed": False,
        "risk_engine_allowed": False,
    }
    atomic_write(asset_dir / "manifest.json", dump_bytes(manifest))

    final_report = {
        "schema_version": "1.0.0",
        "phase": "2L-O7-public-map-accuracy",
        "gate": PASS_GATE,
        "source_zip_sha256": zip_sha,
        "area_metadata_sha256": area_sha,
        "region_count": 142,
        "lods": lod_reports,
        "triangle_floor_policy": "REMOVED",
        "scientific_masking_allowed": False,
        "risk_engine_allowed": False,
    }
    report_payload = json.dumps(final_report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(report_payload, encoding="utf-8")

    print("=" * 82)
    print("LPZ PHASE 2L-O7 — TOPOLOGY-SAFE PUBLIC MAP LOD")
    print("=" * 82)
    for row in lod_reports:
        print(
            f"{row['lod']:<10} regions={row['region_count']} "
            f"vertices={row['display_vertices']:,} size={row['mib']:.2f} MiB "
            f"parts_pruned={row['stats']['polygon_parts_pruned']:,} "
            f"triangle_floors=0"
        )
    print(f"Gate: {PASS_GATE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
