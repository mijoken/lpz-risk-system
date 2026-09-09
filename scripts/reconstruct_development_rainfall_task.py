#!/usr/bin/env python3
"""Run one Phase 2I DEVELOPMENT rainfall task against real provider payloads."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import ftplib
import json
import os
from pathlib import Path
import tempfile
import urllib.request

from lpz_risk.cmorph_v1 import decode_cmorph_cdr_v1_bytes
from lpz_risk.gsmap_v8 import decode_gsmap_gauge_v8_file
from lpz_risk.historical_rainfall_window import build_exact_accumulation_window, build_subdivision_window_descriptor
from lpz_risk.imerg_v07 import decode_imerg_final_v07_file

UTC = timezone.utc
CMORPH_BASE = "https://www.ncei.noaa.gov/data/cmorph-high-resolution-global-precipitation-estimates/access/30min/8km"
GSMAP_BASE = "/standard/v8/hourly_G"


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone-aware time required")
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "lpz-risk-system/0.1 research"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        payload = resp.read()
    if len(payload) < 1024:
        raise ValueError(f"payload unexpectedly small: {url} {len(payload)} bytes")
    return payload


def _load_features(path: Path) -> dict[str, dict]:
    geo = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for f in geo.get("features") or []:
        p = f.get("properties") or {}
        code = str(p.get("primary_subdivision_code", f.get("id", "")))
        if code:
            out[code] = f
    if not out:
        raise ValueError("no official polygon features found")
    return out


def _expected_field_rows(plan: dict, task: dict) -> list[dict]:
    ids = set(task["native_field_ids"])
    rows = [r for r in plan["native_fields"] if r["field_id"] in ids]
    if len(rows) != len(ids):
        raise ValueError("task references unknown native field IDs")
    return rows


def _select_gsmap_filename(names: list[str], dt: datetime) -> str:
    """Resolve one Gauge v8 hourly file from the provider's live directory listing.

    JAXA may change the processing/revision suffix after ``.v8.``.  The timestamp,
    product family, version and gzip/binary format are invariant for this adapter;
    therefore we discover the actual suffix instead of fabricating it.
    """
    prefix = f"gsmap_gauge.{dt:%Y%m%d}.{dt:%H}00.v8."
    candidates = sorted({Path(str(n)).name for n in names if Path(str(n)).name.startswith(prefix) and Path(str(n)).name.endswith(".dat.gz")})
    if not candidates:
        raise FileNotFoundError(
            f"GSMaP Gauge v8 file not present for {_iso(dt)}; directory listing contained {len(names)} entries"
        )
    if len(candidates) > 1:
        raise RuntimeError(f"ambiguous GSMaP Gauge v8 files for {_iso(dt)}: {candidates}")
    return candidates[0]


def _collect_fields_gsmap(task: dict, plan: dict, td: Path) -> dict[str, object]:
    rows = _expected_field_rows(plan, task)
    by_time = {r["valid_start_utc"]: r for r in rows}
    result = {}
    listing_cache: dict[str, list[str]] = {}
    with ftplib.FTP("hokusai.eorc.jaxa.jp", timeout=120) as ftp:
        ftp.login(os.environ["GSMAP_FTP_USERNAME"], os.environ["GSMAP_FTP_PASSWORD"])
        for iso, row in sorted(by_time.items()):
            dt = _parse(iso)
            directory = f"{GSMAP_BASE}/{dt:%Y/%m/%d}"
            if directory not in listing_cache:
                try:
                    listing_cache[directory] = ftp.nlst(directory)
                except ftplib.error_perm as exc:
                    raise FileNotFoundError(f"GSMaP directory unavailable: {directory}: {exc}") from exc
            name = _select_gsmap_filename(listing_cache[directory], dt)
            remote = f"{directory}/{name}"
            local = td / name
            with local.open("wb") as f:
                ftp.retrbinary(f"RETR {remote}", f.write)
            field = decode_gsmap_gauge_v8_file(local)
            if _iso(field.valid_start_utc) != iso:
                raise ValueError(f"GSMaP valid time mismatch for {name}: expected={iso} actual={_iso(field.valid_start_utc)}")
            result[row["field_id"]] = field
            local.unlink(missing_ok=True)
    missing = sorted(set(r["field_id"] for r in rows) - set(result))
    if missing:
        raise RuntimeError(f"GSMaP missing expected native fields: {missing[:5]} count={len(missing)}")
    return result


def _collect_fields_imerg(task: dict, plan: dict, td: Path) -> dict[str, object]:
    import earthaccess

    rows = sorted(_expected_field_rows(plan, task), key=lambda r: r["valid_start_utc"])
    needed = {r["valid_start_utc"]: r for r in rows}
    start = _parse(rows[0]["valid_start_utc"])
    end = _parse(rows[-1]["valid_end_utc"]) - timedelta(seconds=1)
    earthaccess.login(strategy="environment")
    granules = earthaccess.search_data(
        short_name="GPM_3IMERGHH",
        version="07",
        bounding_box=(122.0, 24.0, 150.0, 47.0),
        temporal=(_iso(start), _iso(end)),
        count=80,
    )
    if not granules:
        raise RuntimeError("IMERG search returned no granules")
    dl = td / "imerg"
    paths = earthaccess.download(granules, str(dl), threads=2)
    result = {}
    for raw in paths:
        path = Path(raw)
        field = decode_imerg_final_v07_file(path)
        iso = _iso(field.valid_start_utc)
        row = needed.get(iso)
        if row is not None:
            result[row["field_id"]] = field
        path.unlink(missing_ok=True)
    missing = sorted(set(r["field_id"] for r in rows) - set(result))
    if missing:
        raise RuntimeError(f"IMERG missing expected native fields: {missing[:5]} count={len(missing)}")
    return result


def _collect_fields_cmorph(task: dict, plan: dict, td: Path) -> dict[str, object]:
    rows = _expected_field_rows(plan, task)
    row_by_iso = {r["valid_start_utc"]: r for r in rows}
    payload_ids = set(task["payload_ids"])
    payloads = [p for p in plan["payloads"] if p["payload_id"] in payload_ids]
    if len(payloads) != len(payload_ids):
        raise ValueError("task references unknown CMORPH payload IDs")
    result = {}
    for p in sorted(payloads, key=lambda r: r["payload_time_key"]):
        dt = datetime.strptime(p["payload_time_key"], "%Y%m%d%H").replace(tzinfo=UTC)
        name = f"CMORPH_V1.0_ADJ_8km-30min_{dt:%Y%m%d%H}.nc"
        url = f"{CMORPH_BASE}/{dt:%Y/%m/%d}/{name}"
        payload = _download_bytes(url)
        fields = decode_cmorph_cdr_v1_bytes(payload, filename=name)
        for field in fields:
            iso = _iso(field.valid_start_utc)
            row = row_by_iso.get(iso)
            if row is not None:
                result[row["field_id"]] = field
    missing = sorted(set(r["field_id"] for r in rows) - set(result))
    if missing:
        raise RuntimeError(f"CMORPH missing expected native fields: {missing[:5]} count={len(missing)}")
    return result


def _collect_fields(task: dict, plan: dict, td: Path) -> dict[str, object]:
    source = task["source_id"]
    if source == "GSMAP_STANDARD_V8_HISTORICAL":
        return _collect_fields_gsmap(task, plan, td)
    if source == "NASA_IMERG_FINAL_V07":
        return _collect_fields_imerg(task, plan, td)
    if source == "NOAA_CMORPH_CDR":
        return _collect_fields_cmorph(task, plan, td)
    raise ValueError(f"unsupported source: {source}")


def run_task(plan: dict, manifest: dict, geometry_path: Path, task_id: str) -> dict:
    task = next((t for t in plan["tasks"] if t["task_id"] == task_id), None)
    if task is None:
        raise ValueError(f"unknown task_id: {task_id}")
    if plan.get("split") != "DEVELOPMENT" or manifest.get("split") != "DEVELOPMENT":
        raise ValueError("DEVELOPMENT-only reconstruction")
    features = _load_features(geometry_path)
    windows = {str(w["window_id"]): w for w in manifest["windows"]}
    with tempfile.TemporaryDirectory() as tmp:
        fields = _collect_fields(task, plan, Path(tmp))
        descriptors = []
        for wid in task["window_ids"]:
            w = windows[wid]
            field_ids = plan["window_to_native_field_ids"][wid]
            selected = [fields[fid] for fid in field_ids]
            window = build_exact_accumulation_window(selected, target_seconds=10800)
            code = str(w["primary_subdivision_code"])
            feature = features.get(code)
            if feature is None:
                raise ValueError(f"official polygon unavailable for {code}")
            desc = build_subdivision_window_descriptor(
                window,
                primary_subdivision_code=code,
                polygon_feature=feature,
            )
            descriptors.append({
                "window_id": wid,
                "source_id": w["source_id"],
                "primary_subdivision_code": code,
                "anchor_ids": list(w["anchor_ids"]),
                "local_episode_ids": list(w["local_episode_ids"]),
                "anchor_count": int(w["anchor_count"]),
                "local_episode_count": int(w["local_episode_count"]),
                "minimum_source_lag_seconds": int(w["minimum_source_lag_seconds"]),
                "maximum_source_lag_seconds": int(w["maximum_source_lag_seconds"]),
                "descriptor": desc,
            })

    if len(descriptors) != task["window_count"]:
        raise AssertionError("task did not reconstruct every requested window")
    return {
        "schema_version": "0.2.0",
        "phase": "2I-development-real-rainfall-reconstruction-task",
        "split": "DEVELOPMENT",
        "task_id": task_id,
        "source_id": task["source_id"],
        "window_end_utc_day": task["window_end_utc_day"],
        "expected_window_count": task["window_count"],
        "reconstructed_window_count": len(descriptors),
        "expected_native_field_count": task["native_field_count"],
        "loaded_native_field_count": len(fields),
        "expected_payload_count": task["payload_count"],
        "window_descriptors": descriptors,
        "gsmap_resolution_policy": "LIVE_DIRECTORY_LISTING_TIMESTAMP_AND_PRODUCT_MATCH_NO_FABRICATED_REVISION_SUFFIX",
        "raw_payloads_persisted": False,
        "temporal_resampling_performed": False,
        "cross_source_accumulation_performed": False,
        "candidate_threshold_selected": False,
        "hard_negative_label": None,
        "risk_score": None,
        "risk_engine_allowed": False,
        "gate": "PASS_TASK_REAL_PAYLOAD_RECONSTRUCTION",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan", required=True)
    p.add_argument("--window-manifest", required=True)
    p.add_argument("--geometry", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    try:
        plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
        manifest = json.loads(Path(a.window_manifest).read_text(encoding="utf-8"))
        report = run_task(plan, manifest, Path(a.geometry), a.task_id)
        ok = True
    except Exception as exc:
        report = {
            "schema_version": "0.2.0",
            "phase": "2I-development-real-rainfall-reconstruction-task",
            "task_id": a.task_id,
            "gate": "FAIL_TASK_REAL_PAYLOAD_RECONSTRUCTION",
            "error": f"{type(exc).__name__}: {exc}",
            "risk_engine_allowed": False,
        }
        ok = False
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in (
        "task_id", "source_id", "window_end_utc_day", "expected_window_count",
        "reconstructed_window_count", "expected_native_field_count", "loaded_native_field_count",
        "expected_payload_count", "gate", "error", "risk_engine_allowed") if k in report}, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
