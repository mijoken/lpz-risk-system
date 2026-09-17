#!/usr/bin/env python3
"""IMERG C-0 access probe via NASA CMR.

Research-only connectivity/authentication/content probe.
- Targets GPM_3IMERGHHE V07 (IMERG Early, half-hourly).
- CMR discovers exactly one newest downloadable granule.
- Download requires an Earthdata Bearer token entered via hidden prompt.
- Token is never written to disk or printed.
- Downloads at most one file.
- Does not touch O8.1/O9/Primary/Risk Engine.

Usage:
  python scripts/imerg_c0_access_probe.py --output-dir reports/gap_recovery/c0_imerg
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"
SHORT_NAME = "GPM_3IMERGHHE"
VERSION = "07"
CLIENT_ID = "lpz-risk-system-imerg-c0"
ALLOWED_SUFFIXES = (".h5", ".hdf5", ".nc", ".nc4")


def safe_name(url: str) -> str:
    name = Path(urlparse(url).path).name or "imerg_probe.bin"
    return name.replace("..", "_")


def inspect_hdf5(path: Path) -> dict:
    try:
        import h5py
        datasets = []
        with h5py.File(path, "r") as h:
            def visit(name, obj):
                if isinstance(obj, h5py.Dataset):
                    datasets.append({
                        "path": name,
                        "shape": list(obj.shape),
                        "dtype": str(obj.dtype),
                    })
            h.visititems(visit)
        return {"opened": True, "datasets": datasets[:200], "dataset_count": len(datasets)}
    except Exception as exc:
        return {"opened": False, "error": f"{type(exc).__name__}: {exc}"}


def discover_latest() -> tuple[dict, str]:
    params = {
        "short_name": SHORT_NAME,
        "version": VERSION,
        "downloadable": "true",
        "page_size": 1,
        "sort_key[]": "-start_date",
    }
    headers = {"Accept": "application/json", "Client-Id": CLIENT_ID}
    response = requests.get(CMR_URL, params=params, headers=headers, timeout=60)
    response.raise_for_status()
    payload = response.json()
    items = payload.get("items", [])
    if not items:
        raise RuntimeError("CMR returned no downloadable granules")

    item = items[0]
    umm = item.get("umm", {})
    candidates = []
    for related in umm.get("RelatedUrls", []):
        if related.get("Type") == "GET DATA" and related.get("URL"):
            candidates.append(related["URL"])
    if not candidates:
        raise RuntimeError("Newest CMR granule has no GET DATA URL")

    # Prefer a direct data file over documentation/service links if multiple exist.
    def score(url: str) -> tuple[int, int]:
        path = urlparse(url).path.lower()
        suffix_match = any(path.endswith(s) for s in ALLOWED_SUFFIXES)
        return (1 if suffix_match else 0, len(path))

    selected = sorted(candidates, key=score, reverse=True)[0]
    info = {
        "cmr_hits": payload.get("hits"),
        "concept_id": item.get("meta", {}).get("concept-id"),
        "granule_ur": umm.get("GranuleUR"),
        "temporal_extent": umm.get("TemporalExtent"),
        "provider_dates": umm.get("ProviderDates"),
        "get_data_url_count": len(candidates),
        "selected_host": urlparse(selected).hostname,
        "selected_path": urlparse(selected).path,
    }
    return info, selected


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path, default=Path("reports/gap_recovery/c0_imerg"))
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--discover-only", action="store_true", help="Discover newest granule but do not request credentials or download")
    args = ap.parse_args()

    meta = {
        "schema_version": "0.2.0-imerg-c0",
        "role": "RESEARCH_ONLY_CMR_ACCESS_PROBE",
        "collection": {"short_name": SHORT_NAME, "version": VERSION},
        "credentials_persisted": False,
        "maximum_download_files": 1,
        "risk_engine_allowed": False,
    }

    try:
        granule, url = discover_latest()
        meta["discovery"] = granule
        if args.discover_only:
            meta["result"] = "DISCOVERY_OK_NO_DOWNLOAD"
            print(json.dumps(meta, ensure_ascii=False, indent=2))
            return 0

        token = getpass.getpass("Earthdata Bearer token (hidden; not stored): ").strip()
        if not token:
            raise RuntimeError("empty Earthdata Bearer token")

        args.output_dir.mkdir(parents=True, exist_ok=True)
        dst = args.output_dir / safe_name(url)
        tmp = dst.with_suffix(dst.suffix + ".part")
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": f"{CLIENT_ID}/0.2",
        }
        try:
            with requests.get(url, headers=headers, stream=True, timeout=args.timeout, allow_redirects=True) as response:
                meta["download"] = {
                    "http_status": response.status_code,
                    "final_host": urlparse(response.url).hostname,
                    "content_type": response.headers.get("Content-Type"),
                    "content_length_header": response.headers.get("Content-Length"),
                    "redirect_history": [
                        {"status": x.status_code, "host": urlparse(x.url).hostname}
                        for x in response.history
                    ],
                }
                if response.status_code != 200:
                    meta["result"] = "HTTP_FAILURE"
                    print(json.dumps(meta, ensure_ascii=False, indent=2))
                    return 2

                digest = hashlib.sha256()
                nbytes = 0
                with tmp.open("wb") as f:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            digest.update(chunk)
                            nbytes += len(chunk)

            os.replace(tmp, dst)
            meta["result"] = "DOWNLOAD_OK"
            meta["download"].update({
                "filename": dst.name,
                "bytes": nbytes,
                "sha256": digest.hexdigest(),
            })
            if dst.suffix.lower() in ALLOWED_SUFFIXES:
                meta["hdf5_inspection"] = inspect_hdf5(dst)
            (args.output_dir / "probe_result.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            print(json.dumps(meta, ensure_ascii=False, indent=2))
            return 0
        finally:
            token = ""
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    except Exception as exc:
        meta["result"] = "PROBE_FAILURE"
        meta["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
