#!/usr/bin/env python3
"""Phase 2L-O2 — build lightweight public JMA primary-subdivision GeoJSON.

Display geometry only. Never use this output for scientific masking, matching,
validation, or risk calculation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lpz_risk.historical_spatial import build_primary_subdivision_geojson

DEFAULT_CONFIG = ROOT / "config" / "jma_primary_subdivision_gis.json"
DEFAULT_OUTPUT = ROOT / "web" / "assets" / "japan_primary_subdivisions.geojson"
DEFAULT_REPORT = ROOT / "reports" / "web" / "phase2l_o2_public_geometry_report.json"

PASS_GATE = "PASS_PHASE2L_O2_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOJSON"
FAIL_TOO_LARGE = "FAIL_PHASE2L_O2_PUBLIC_GEOJSON_TOO_LARGE"
FAIL_NON_MONOTONIC = "FAIL_PHASE2L_O2_NON_MONOTONIC_SIMPLIFICATION"
MAX_DECIMALS = 10


def download(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "lpz-risk-system/0.1 public-map-builder"},
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        payload = response.read()
    if not payload:
        raise ValueError(f"empty response: {url}")
    return payload


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def dump_bytes(obj: Any) -> bytes:
    return (
        json.dumps(
            obj,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    tmp.replace(path)


def extract_class10s(payload: bytes) -> dict[str, dict[str, Any]]:
    obj = json.loads(payload.decode("utf-8"))
    source = obj.get("class10s")
    if not isinstance(source, dict) or not source:
        raise ValueError("JMA area.json missing class10s")

    out: dict[str, dict[str, Any]] = {}
    for raw_code, meta in source.items():
        code = str(raw_code)
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"bad class10s code: {code}")
        if not isinstance(meta, dict) or not str(meta.get("name", "")).strip():
            raise ValueError(f"bad class10s metadata: {code}")
        out[code] = meta
    return out


def point_segment_d2(p, a, b) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx = bx - ax
    dy = by - ay
    if dx == 0.0 and dy == 0.0:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = max(
        0.0,
        min(
            1.0,
            ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy),
        ),
    )
    qx = ax + t * dx
    qy = ay + t * dy
    return (px - qx) ** 2 + (py - qy) ** 2


def rdp(points, tolerance: float):
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


def open_ring(coords):
    points = []
    for p in coords:
        q = [float(p[0]), float(p[1])]
        if not points or q != points[-1]:
            points.append(q)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


def close_round(points, decimals: int):
    out = []
    for p in points:
        q = [round(float(p[0]), decimals), round(float(p[1]), decimals)]
        if not out or q != out[-1]:
            out.append(q)
    if out and out[0] != out[-1]:
        out.append(out[0][:])
    return out


def valid_ring(ring) -> bool:
    return (
        len(ring) >= 4
        and ring[0] == ring[-1]
        and len({tuple(p) for p in ring[:-1]}) >= 3
        and all(
            118.0 <= p[0] <= 156.0 and 18.0 <= p[1] <= 50.0
            for p in ring
        )
    )


def minimal_triangle(points):
    """Choose three source vertices in original cyclic order.

    Used only for browser-display fallback when RDP would collapse a closed ring
    below three distinct vertices.
    """
    if len({tuple(p) for p in points}) < 3:
        raise ValueError("degenerate official ring")

    i0 = min(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    p0 = points[i0]
    i1 = max(
        range(len(points)),
        key=lambda i: (
            (points[i][0] - p0[0]) ** 2 + (points[i][1] - p0[1]) ** 2
        ),
    )
    candidates = [i for i in range(len(points)) if i not in {i0, i1}]
    if not candidates:
        raise ValueError("triangle fallback has fewer than three candidates")

    i2 = max(
        candidates,
        key=lambda i: point_segment_d2(points[i], points[i0], points[i1]),
    )
    if point_segment_d2(points[i2], points[i0], points[i1]) <= 0.0:
        raise ValueError("degenerate official ring")

    chosen = {i0, i1, i2}
    triangle = [points[i] for i in range(len(points)) if i in chosen]
    if len(triangle) != 3:
        raise ValueError("triangle fallback failed")
    return triangle


def simplify_open_ring(points, tolerance: float):
    """Simplify a closed ring represented without its closing point.

    Critical invariant:
    a large tolerance must never revert to the full original ring. If RDP
    collapses to fewer than three vertices, retain a three-vertex display
    approximation chosen from the original official ring.
    """
    if len(points) <= 3:
        return points[:]

    i0 = min(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    p0 = points[i0]
    i1 = max(
        range(len(points)),
        key=lambda i: (
            (points[i][0] - p0[0]) ** 2 + (points[i][1] - p0[1]) ** 2
        ),
    )

    rotated = points[i0:] + points[:i0]
    j = (i1 - i0) % len(points)
    if j <= 0 or j >= len(rotated):
        j = max(
            range(1, len(rotated)),
            key=lambda i: (
                (rotated[i][0] - rotated[0][0]) ** 2
                + (rotated[i][1] - rotated[0][1]) ** 2
            ),
        )

    merged = (
        rdp(rotated[: j + 1], tolerance)
        + rdp(rotated[j:] + [rotated[0]], tolerance)[1:]
    )

    deduped = []
    for p in merged:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    if deduped and deduped[0] == deduped[-1]:
        deduped.pop()

    if len({tuple(p) for p in deduped}) >= 3:
        return deduped

    return minimal_triangle(points)


def simplify_ring(coords, tolerance: float, decimals: int, stats: dict[str, int]):
    stats["rings_total"] += 1
    points = open_ring(coords)
    if len({tuple(p) for p in points}) < 3:
        raise ValueError("official ring invalid")

    simplified = simplify_open_ring(points, tolerance)
    candidate = close_round(simplified, decimals)
    if valid_ring(candidate):
        if len(candidate) - 1 < len(points):
            stats["rings_simplified"] += 1
        if len(simplified) == 3 and len(points) > 3:
            stats["rings_three_vertex_floor"] += 1
        return candidate

    # Decimal rounding can still collapse an extremely small island.
    stats["rings_precision_fallback"] += 1
    triangle = minimal_triangle(points)
    for d in range(decimals, MAX_DECIMALS + 1):
        ring = close_round(triangle, d)
        if valid_ring(ring):
            if d > decimals:
                stats["rings_precision_escalated"] += 1
            stats["max_decimals_used"] = max(stats["max_decimals_used"], d)
            return ring

    exact = triangle + [triangle[0][:]]
    if valid_ring(exact):
        stats["rings_exact_triangle"] += 1
        return exact
    raise ValueError("tiny ring fallback invalid")


def transform_geometry(geometry, tolerance: float, decimals: int, stats):
    kind = geometry.get("type")
    if kind == "Polygon":
        return {
            "type": "Polygon",
            "coordinates": [
                simplify_ring(r, tolerance, decimals, stats)
                for r in geometry.get("coordinates", [])
            ],
        }
    if kind == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [
                [
                    simplify_ring(r, tolerance, decimals, stats)
                    for r in polygon
                ]
                for polygon in geometry.get("coordinates", [])
            ],
        }
    if kind == "GeometryCollection":
        return {
            "type": "GeometryCollection",
            "geometries": [
                transform_geometry(g, tolerance, decimals, stats)
                for g in geometry.get("geometries", [])
            ],
        }
    raise ValueError(f"unsupported geometry: {kind}")


def count_vertices(geometry) -> int:
    kind = geometry.get("type")
    if kind == "Polygon":
        return sum(len(r) for r in geometry.get("coordinates", []))
    if kind == "MultiPolygon":
        return sum(
            len(r)
            for polygon in geometry.get("coordinates", [])
            for r in polygon
        )
    if kind == "GeometryCollection":
        return sum(count_vertices(g) for g in geometry.get("geometries", []))
    raise ValueError(kind)


def validate_geometry(geometry) -> None:
    kind = geometry.get("type")
    if kind == "Polygon":
        polygons = [geometry.get("coordinates", [])]
    elif kind == "MultiPolygon":
        polygons = geometry.get("coordinates", [])
    elif kind == "GeometryCollection":
        for g in geometry.get("geometries", []):
            validate_geometry(g)
        return
    else:
        raise ValueError(kind)

    for polygon in polygons:
        if not polygon:
            raise ValueError("polygon without rings")
        for ring in polygon:
            if not valid_ring(ring):
                raise ValueError("invalid display ring")


def build_candidate(
    official,
    metadata,
    config,
    tolerance: float,
    decimals: int,
    zip_sha: str,
    area_sha: str,
):
    stats = {
        "rings_total": 0,
        "rings_simplified": 0,
        "rings_three_vertex_floor": 0,
        "rings_precision_fallback": 0,
        "rings_precision_escalated": 0,
        "rings_exact_triangle": 0,
        "max_decimals_used": decimals,
    }

    features = []
    before = 0
    after = 0
    seen = set()

    for feature in official["features"]:
        code = str(feature["id"])
        if code not in metadata or code in seen:
            raise RuntimeError(f"bad/duplicate code {code}")
        seen.add(code)

        raw_geometry = feature["geometry"]
        display_geometry = transform_geometry(
            raw_geometry,
            tolerance,
            decimals,
            stats,
        )
        validate_geometry(display_geometry)

        before += count_vertices(raw_geometry)
        after += count_vertices(display_geometry)

        props = feature.get("properties", {})
        features.append(
            {
                "type": "Feature",
                "id": code,
                "properties": {
                    "region_code": code,
                    "geometry_key": code,
                    "name_ja": metadata[code].get("name"),
                    "name_en": metadata[code].get("enName"),
                    "parent_code": metadata[code].get("parent"),
                    "office_name_ja": metadata[code].get("officeName"),
                    "source_part_count": props.get("source_part_count"),
                },
                "geometry": display_geometry,
            }
        )

    if seen != set(metadata):
        raise RuntimeError("public feature code mismatch")

    features.sort(key=lambda x: x["id"])
    obj = {
        "type": "FeatureCollection",
        "schema_version": "1.0.3",
        "product": "LPZ_PUBLIC_JMA_PRIMARY_SUBDIVISION_GEOMETRY",
        "geographic_unit": "JMA_PRIMARY_SUBDIVISION",
        "geometry_key": "region_code",
        "display_geometry_semantics": (
            "AUTO_SIMPLIFIED_DERIVATIVE_FOR_WEB_DISPLAY_ONLY"
        ),
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
            "simplification_algorithm": (
                "RDP_AUTO_TUNED_MONOTONIC_WITH_THREE_VERTEX_FLOOR"
            ),
            "tolerance_degrees": tolerance,
            "nominal_coordinate_decimals": decimals,
            "adaptive_precision_max_decimals": MAX_DECIMALS,
            "collapsed_ring_policy": (
                "DISPLAY_ONLY_KEEP_THREE_SOURCE_VERTICES_NEVER_RESTORE_FULL_RING"
            ),
            "research_geometry_modified": False,
        },
        "region_count": len(features),
        "features": features,
    }
    return obj, {"before": before, "after": after, "stats": stats}


def tolerance_schedule(base: float, maximum: float) -> list[float]:
    values = []
    value = base
    while value <= maximum + 1e-12:
        values.append(round(value, 10))
        value *= 2.0
    if not values or values[-1] < maximum:
        values.append(maximum)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--tolerance-deg", type=float, default=0.0015)
    parser.add_argument("--max-tolerance-deg", type=float, default=0.096)
    parser.add_argument("--coordinate-decimals", type=int, default=5)
    parser.add_argument("--target-output-mib", type=float, default=8.0)
    parser.add_argument("--max-output-mib", type=float, default=10.0)
    args = parser.parse_args()

    if args.tolerance_deg <= 0 or args.max_tolerance_deg < args.tolerance_deg:
        raise ValueError("invalid tolerance range")
    if not 4 <= args.coordinate_decimals <= 8:
        raise ValueError("coordinate decimals must be 4..8")
    if not 0 < args.target_output_mib <= args.max_output_mib:
        raise ValueError("invalid size limits")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config.get("source_id") != "JMA_PRIMARY_SUBDIVISION_GIS":
        raise ValueError("unexpected source_id")

    print("=" * 104)
    print("LPZ PHASE 2L-O2 — PUBLIC JMA PRIMARY-SUBDIVISION GEOJSON")
    print("=" * 104)

    print("Downloading JMA area metadata ...")
    area_payload = download(str(config["area_metadata_url"]))
    metadata = extract_class10s(area_payload)
    codes = set(metadata)
    print(f"JMA class10s regions             : {len(codes)}")

    print("Downloading official JMA primary-subdivision GIS archive ...")
    zip_payload = download(str(config["zip_url"]))
    print(
        f"GIS archive downloaded           : "
        f"{len(zip_payload) / (1024 ** 2):.1f} MiB"
    )

    official = build_primary_subdivision_geojson(zip_payload, codes)
    missing = list(official.get("missing_required_codes") or [])
    if missing or int(official.get("resolved_code_count", -1)) != len(codes):
        raise RuntimeError(f"official geometry incomplete: {missing[:20]}")

    print(f"Official geometry resolved       : {len(codes)} / {len(codes)}")
    print(
        f"Auto-size target / hard max      : "
        f"{args.target_output_mib:.2f} / {args.max_output_mib:.2f} MiB"
    )
    print("-" * 104)

    trials = []
    chosen = None
    best = None
    previous_after = None
    previous_tolerance = None

    zip_sha = sha256(zip_payload)
    area_sha = sha256(area_payload)

    for tolerance in tolerance_schedule(
        args.tolerance_deg,
        args.max_tolerance_deg,
    ):
        obj, metrics = build_candidate(
            official,
            metadata,
            config,
            tolerance,
            args.coordinate_decimals,
            zip_sha,
            area_sha,
        )
        payload = dump_bytes(obj)
        size_mib = len(payload) / (1024 ** 2)
        ratio = (
            metrics["after"] / metrics["before"]
            if metrics["before"]
            else 0.0
        )

        if previous_after is not None and metrics["after"] > previous_after:
            report = {
                "schema_version": "1.0.3",
                "phase": "2L-O2-public-primary-subdivision-geometry",
                "gate": FAIL_NON_MONOTONIC,
                "previous_tolerance_degrees": previous_tolerance,
                "previous_after_vertices": previous_after,
                "current_tolerance_degrees": tolerance,
                "current_after_vertices": metrics["after"],
                "trials": trials,
                "scientific_masking_allowed": False,
                "research_geometry_modified": False,
                "risk_engine_allowed": False,
            }
            atomic_write(
                args.report,
                (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            raise RuntimeError(
                "non-monotonic simplification detected: "
                f"{previous_after:,} -> {metrics['after']:,} vertices"
            )

        trials.append(
            {
                "tolerance_degrees": tolerance,
                "output_size_mib": size_mib,
                "after_vertices": metrics["after"],
                "vertex_retention_fraction": ratio,
                "ring_fallback_statistics": metrics["stats"],
            }
        )
        print(
            f"trial tolerance={tolerance:<8g} "
            f"size={size_mib:>7.2f} MiB "
            f"vertices={metrics['after']:,} "
            f"retention={ratio:.2%}"
        )

        previous_after = metrics["after"]
        previous_tolerance = tolerance

        if size_mib <= args.max_output_mib:
            best = (tolerance, obj, metrics, payload)
        if size_mib <= args.target_output_mib:
            chosen = (tolerance, obj, metrics, payload)
            break

    if chosen is None:
        chosen = best

    if chosen is None:
        report = {
            "schema_version": "1.0.3",
            "phase": "2L-O2-public-primary-subdivision-geometry",
            "gate": FAIL_TOO_LARGE,
            "trials": trials,
            "scientific_masking_allowed": False,
            "research_geometry_modified": False,
            "risk_engine_allowed": False,
        }
        atomic_write(
            args.report,
            (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
        raise RuntimeError(
            f"no safe simplification fit under {args.max_output_mib:.2f} MiB; see report"
        )

    tolerance, obj, metrics, payload = chosen
    atomic_write(args.output, payload)

    size_mib = len(payload) / (1024 ** 2)
    ratio = metrics["after"] / metrics["before"] if metrics["before"] else 0.0
    stats = metrics["stats"]

    report = {
        "schema_version": "1.0.3",
        "phase": "2L-O2-public-primary-subdivision-geometry",
        "gate": PASS_GATE,
        "jma_class10s_count": len(codes),
        "official_geometry_resolved_count": len(codes),
        "output": str(args.output),
        "output_size_mib": size_mib,
        "official_vertex_count_before_display_transform": metrics["before"],
        "public_vertex_count_after_display_transform": metrics["after"],
        "vertex_retention_fraction": ratio,
        "initial_tolerance_degrees": args.tolerance_deg,
        "selected_tolerance_degrees": tolerance,
        "ring_fallback_statistics": stats,
        "auto_tuning_trials": trials,
        "scientific_masking_allowed": False,
        "research_geometry_modified": False,
        "risk_engine_allowed": False,
        "source_zip_sha256": zip_sha,
        "area_metadata_sha256": area_sha,
    }
    atomic_write(
        args.report,
        (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )

    print("-" * 104)
    print(f"Selected display tolerance       : {tolerance:g} deg")
    print(f"Vertices before display simplify : {metrics['before']:,}")
    print(f"Vertices after display simplify  : {metrics['after']:,}")
    print(f"Vertex retention                 : {ratio:.2%}")
    print(f"Three-vertex floor rings         : {stats['rings_three_vertex_floor']:,}")
    print(f"Precision-fallback rings         : {stats['rings_precision_fallback']:,}")
    print(f"Precision-escalated rings        : {stats['rings_precision_escalated']:,}")
    print(f"Maximum decimals actually used   : {stats['max_decimals_used']}")
    print(f"Public GeoJSON size              : {size_mib:.2f} MiB")
    print("Scientific masking allowed       : NO")
    print("Research geometry modified       : NO")
    print("Risk engine                      : NOT ALLOWED")
    print()
    print(f"Gate                             : {PASS_GATE}")
    print(f"GeoJSON                          : {args.output}")
    print(f"Report                           : {args.report}")
    print("=" * 104)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
