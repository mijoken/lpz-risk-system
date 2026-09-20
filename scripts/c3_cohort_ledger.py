"""Immutable local ledger for the research-only C-3 prospective cohort."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import uuid


SUCCESS_STATUSES = frozenset({
    "CAPTURED_VERIFIED",
    "REUSED_VERIFIED",
})


def _now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    """Create a new record without replacing any existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            value,
            stream,
            ensure_ascii=False,
            indent=2,
        )
        stream.write("\n")


def register_attempt(
    result: dict[str, Any],
    evidence_root: Path,
) -> dict[str, Any]:
    """Preserve each attempted slot outcome and its verified success record."""

    slot = result["collection_slot_utc"]

    slot_id = (
        slot.replace("-", "")
        .replace(":", "")
        .replace("T", "T")
    )

    if not slot_id.endswith("Z"):
        raise ValueError("C3_SLOT_NOT_UTC")

    status = result["status"]

    if status not in (
        SUCCESS_STATUSES
        | {"MISSING_JMA_FRAME", "CAPTURE_FAILED"}
    ):
        raise ValueError(f"C3_UNKNOWN_STATUS: {status}")

    if result.get("research_only") is not True:
        raise ValueError("C3_RESEARCH_LOCK_MISSING")

    if result.get("risk_engine_allowed") is not False:
        raise ValueError("C3_RISK_ENGINE_LOCK_MISSING")

    registered_at = _now_utc()

    attempt = {
        "schema_version": "0.1.0-c3-cohort-attempt",
        "cohort": "C-3_PROSPECTIVE_MULTI_EVENT",
        "collection_slot_utc": slot,
        "support_start_utc": result["support_start_utc"],
        "status": status,
        "raw_radar_archived": result["raw_radar_archived"],
        "expected_frames": 7,
        "expected_png": 343,
        "verified_png": result.get("verified_png", 0),
        "error": result.get("error"),
        "capture_dir": result["capture_dir"],
        "manifest_path": result["manifest_path"],
        "registered_at_utc": registered_at,
        "research_only": True,
        "risk_engine_allowed": False,
    }

    attempts_dir = evidence_root / "cohort_attempts" / slot_id

    attempt_path = (
        attempts_dir
        / (
            registered_at
            .replace(":", "")
            .replace("-", "")
            .replace(".", "")
            + "_"
            + uuid.uuid4().hex
            + ".json"
        )
    )

    # The attempt is written first, including failures.
    _write_exclusive(attempt_path, attempt)

    registration = {
        "attempt_path": str(attempt_path),
        "success_ledger_path": None,
        "registration_state": "ATTEMPT_RECORDED",
    }

    if status not in SUCCESS_STATUSES:
        return registration

    if result.get("raw_radar_archived") is not True:
        raise ValueError("C3_SUCCESS_WITHOUT_ARCHIVE")

    if result.get("verified_png") != 343:
        raise ValueError("C3_SUCCESS_WITHOUT_343_VERIFIED_PNG")

    manifest_path = Path(result["manifest_path"])

    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    success_path = (
        evidence_root
        / "cohort_slots"
        / f"{slot_id}.json"
    )

    registration["success_ledger_path"] = str(success_path)

    if success_path.exists():
        existing = json.loads(
            success_path.read_text(encoding="utf-8")
        )

        if (
            existing.get("manifest_sha256")
            != manifest_sha
        ):
            raise ValueError(
                "C3_SUCCESS_LEDGER_MANIFEST_CONFLICT"
            )

        if (
            existing.get("collection_slot_utc")
            != slot
        ):
            raise ValueError(
                "C3_SUCCESS_LEDGER_SLOT_CONFLICT"
            )

        registration["registration_state"] = (
            "EXISTING_SUCCESS_PRESERVED"
        )

        return registration

    success = {
        "schema_version": "0.1.0-c3-cohort-slot",
        "cohort": "C-3_PROSPECTIVE_MULTI_EVENT",
        "collection_slot_utc": slot,
        "support_start_utc": result["support_start_utc"],
        "support_end_utc": slot,
        "fixed_utc_hours": [0, 6, 12, 18],
        "frame_count": 7,
        "expected_png": 343,
        "verified_png": 343,
        "status": status,
        "raw_radar_archived": True,
        "research_only": True,
        "risk_engine_allowed": False,
        "capture_dir": result["capture_dir"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "registered_at_utc": registered_at,
        "registration_type": "AUTOMATED_FORMAL_COHORT_SLOT",
    }

    try:
        _write_exclusive(success_path, success)

    except FileExistsError:
        # A concurrent writer may have created the slot.
        existing = json.loads(
            success_path.read_text(encoding="utf-8")
        )

        if (
            existing.get("manifest_sha256")
            != manifest_sha
            or existing.get("collection_slot_utc")
            != slot
        ):
            raise ValueError(
                "C3_CONCURRENT_SUCCESS_LEDGER_CONFLICT"
            )

        registration["registration_state"] = (
            "EXISTING_SUCCESS_PRESERVED"
        )

        return registration

    registration["registration_state"] = (
        "NEW_SUCCESS_REGISTERED"
    )

    return registration
