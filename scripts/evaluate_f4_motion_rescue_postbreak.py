#!/usr/bin/env python3
"""F4-6C retrospective audit of motion-rescue candidates after an identity break.

Primary gate is frozen from F4-6B before this audit:
- motion error <= 8 px
- observable top-1-to-second candidate margin >= 3 px
- source/candidate not boundary truncated

For each selected UNIQUE zero-overlap break event, inspect only archived
observations after the break:
1) whether the proposed candidate already has an incoming primary-match owner
   from another previous component at the break transition;
2) how many later 5-minute steps the candidate can be followed through the
   EXISTING overlap-based primary-match tracker.

This is research diagnostics only. It does not verify identity, create rescue
links, alter production tracking, or generate LPZ risk/forecast output.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from build_f4_research_motion_baseline import utc
from evaluate_f4_motion_rescue_candidates import evaluate as evaluate_rescue
from trace_f4_radar_identity_across_slots import _frames, _signature


PRIMARY_DISTANCE_GATE_PIXELS = 8.0
PRIMARY_MARGIN_GATE_PIXELS = 3.0
MAX_FORWARD_STEPS = 3


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _slot_filename(value: str) -> str:
    return utc(value).strftime("%Y%m%dT%H%M%SZ.json")


def _load_bundles(batch_roots: list[Path]) -> list[tuple[str, dict]]:
    out = []
    for root in batch_roots:
        manifest = _read(root / "batch_manifest.json")
        if manifest.get("risk_engine_allowed") is not False:
            raise ValueError("batch risk lock not proven")
        run_id = str(manifest.get("run_id") or "")
        if not run_id:
            raise ValueError("batch run_id missing")
        rows = manifest.get("slot_results")
        if not isinstance(rows, list):
            raise ValueError("batch slot_results missing")
        for row in rows:
            slot = row.get("collection_slot_utc")
            if not isinstance(slot, str):
                raise ValueError("slot timestamp missing")
            path = root / "slots" / _slot_filename(slot)
            bundle = _read(path)
            if bundle.get("collection_slot_utc") != slot:
                raise ValueError("bundle slot mismatch")
            # _frames enforces O8.1 research safety contract.
            _frames(bundle)
            out.append((run_id, bundle))
    return out


def _build_archive_index(
    bundles: list[tuple[str, dict]],
    reference_grid: dict,
) -> tuple[dict[str, dict], dict[tuple[str, str], list[tuple[list, dict]]]]:
    frames: dict[str, dict] = {}
    edges: dict[tuple[str, str], list[tuple[list, dict]]] = {}

    for _run_id, bundle in bundles:
        radar = bundle["components"]["radar_tracking"]
        if radar["fixed_mosaic"] != reference_grid:
            continue
        fs = _frames(bundle)

        for frame in fs:
            time = frame["valid_time"]
            components = {_signature(c): c for c in frame["components"]}
            if len(components) != len(frame["components"]):
                raise ValueError("duplicate observed component signature")
            if time in frames and set(frames[time]) != set(components):
                raise ValueError("conflicting overlapping archived frame")
            frames[time] = components

        for transition in radar["tracking"]["30"].get("transitions", []):
            a = transition["from_valid_time"]
            b = transition["to_valid_time"]
            if utc(b) - utc(a) != timedelta(minutes=5):
                continue
            edges.setdefault((a, b), []).append((fs, transition))

    return frames, edges


def _component_by_local_id(frame_components: dict, local_id: int) -> tuple | None:
    matches = [
        signature
        for signature, component in frame_components.items()
        if int(component["local_id"]) == int(local_id)
    ]
    if len(matches) == 0:
        return None
    if len(matches) > 1:
        raise ValueError("duplicate local_id within archived frame")
    return matches[0]


def _incoming_primary_owners(
    frames: dict[str, dict],
    edges: dict[tuple[str, str], list[tuple[list, dict]]],
    a: str,
    b: str,
    candidate_signature: tuple,
) -> set[tuple]:
    owners: set[tuple] = set()
    candidate_local_id = int(frames[b][candidate_signature]["local_id"])

    for fs, transition in edges.get((a, b), []):
        prev_frame = next((f for f in fs if f["valid_time"] == a), None)
        curr_frame = next((f for f in fs if f["valid_time"] == b), None)
        if prev_frame is None or curr_frame is None:
            raise ValueError("break transition frames absent")

        current_candidates = [
            c for c in curr_frame["components"]
            if int(c["local_id"]) == candidate_local_id
        ]
        if len(current_candidates) != 1:
            raise ValueError("candidate local_id ambiguous in break frame")
        if _signature(current_candidates[0]) != candidate_signature:
            raise ValueError("candidate signature mismatch across archive")

        for match in transition.get("primary_matches", []):
            if int(match["current_id"]) != candidate_local_id:
                continue
            previous = [
                c for c in prev_frame["components"]
                if int(c["local_id"]) == int(match["previous_id"])
            ]
            if len(previous) != 1:
                raise ValueError("incoming primary owner ambiguous")
            owners.add(_signature(previous[0]))

    return owners


def _follow_primary_chain(
    frames: dict[str, dict],
    edges: dict[tuple[str, str], list[tuple[list, dict]]],
    start_time_utc: str,
    start_signature: tuple,
) -> dict:
    current_time = utc(start_time_utc)
    current_signature = start_signature
    steps = []
    stop_reason = None

    for _ in range(MAX_FORWARD_STEPS):
        next_time = current_time + timedelta(minutes=5)
        a = current_time.isoformat().replace("+00:00", "Z")
        b = next_time.isoformat().replace("+00:00", "Z")

        if a not in frames or b not in frames:
            stop_reason = "NO_ARCHIVED_NEXT_FRAME"
            break
        if current_signature not in frames[a]:
            raise ValueError("current candidate missing from archived frame")

        current_local_id = int(frames[a][current_signature]["local_id"])
        matches: set[tuple] = set()

        for fs, transition in edges.get((a, b), []):
            curr_frame = next((f for f in fs if f["valid_time"] == b), None)
            if curr_frame is None:
                raise ValueError("forward transition current frame absent")
            for match in transition.get("primary_matches", []):
                if int(match["previous_id"]) != current_local_id:
                    continue
                candidates = [
                    c for c in curr_frame["components"]
                    if int(c["local_id"]) == int(match["current_id"])
                ]
                if len(candidates) != 1:
                    raise ValueError("forward primary target ambiguous")
                matches.add(_signature(candidates[0]))

        if len(matches) == 0:
            stop_reason = "NO_FORWARD_PRIMARY_MATCH"
            break
        if len(matches) > 1:
            stop_reason = "CONFLICTING_FORWARD_PRIMARY_MATCHES"
            break

        next_signature = next(iter(matches))
        if next_signature not in frames[b]:
            raise ValueError("forward target differs from archived observation")

        steps.append({
            "from_valid_time_utc": a,
            "to_valid_time_utc": b,
            "target_component_signature": list(next_signature),
        })
        current_time = next_time
        current_signature = next_signature

    if len(steps) == MAX_FORWARD_STEPS:
        stop_reason = "MAX_AUDIT_HORIZON_REACHED"

    return {
        "forward_primary_continuity_steps": len(steps),
        "forward_primary_continuity_minutes": len(steps) * 5,
        "forward_steps": steps,
        "forward_stop_reason": stop_reason,
    }


def _passes_primary_gate(event: dict) -> bool:
    if not event.get("motion_reference_available"):
        return False
    if event.get("previous_component_boundary_truncated") is True:
        return False
    if event.get("candidate_boundary_truncated") is not False:
        return False
    error = event.get("motion_error_pixels")
    if error is None or float(error) > PRIMARY_DISTANCE_GATE_PIXELS:
        return False
    margin = event.get("competitor_margin_pixels")
    if margin is not None and float(margin) < PRIMARY_MARGIN_GATE_PIXELS:
        return False
    return True


def _audit_event(
    event: dict,
    frames: dict[str, dict],
    edges: dict[tuple[str, str], list[tuple[list, dict]]],
) -> dict:
    a = event["break_from_valid_time_utc"]
    b = event["break_to_valid_time_utc"]
    if a not in frames or b not in frames:
        return {
            **event,
            "audit_status": "BREAK_FRAME_MISSING",
            "candidate_signature": None,
            "incoming_primary_owner_count": None,
            "incoming_primary_owner_conflict": None,
            "forward_primary_continuity_steps": 0,
            "forward_primary_continuity_minutes": 0,
            "forward_steps": [],
            "forward_stop_reason": "BREAK_FRAME_MISSING",
        }

    candidate_local_id = event.get("candidate_local_id")
    candidate_signature = _component_by_local_id(
        frames[b], int(candidate_local_id)
    )
    if candidate_signature is None:
        return {
            **event,
            "audit_status": "CANDIDATE_NOT_FOUND_IN_BREAK_TARGET_FRAME",
            "candidate_signature": None,
            "incoming_primary_owner_count": None,
            "incoming_primary_owner_conflict": None,
            "forward_primary_continuity_steps": 0,
            "forward_primary_continuity_minutes": 0,
            "forward_steps": [],
            "forward_stop_reason": "CANDIDATE_NOT_FOUND",
        }

    owners = _incoming_primary_owners(
        frames, edges, a, b, candidate_signature
    )
    forward = _follow_primary_chain(
        frames, edges, b, candidate_signature
    )

    return {
        **event,
        "audit_status": "AUDITED",
        "candidate_signature": list(candidate_signature),
        "incoming_primary_owner_count": len(owners),
        "incoming_primary_owner_conflict": len(owners) > 0,
        "incoming_primary_owner_signatures": [
            list(signature) for signature in sorted(owners, key=repr)
        ],
        **forward,
    }


def evaluate(
    source_root: Path,
    comparison_roots: list[Path],
    all_batch_roots: list[Path],
) -> dict:
    rescue = evaluate_rescue(
        source_root,
        comparison_roots,
        all_batch_roots,
    )

    if (
        rescue.get("schema_version") != "0.2.0"
        or rescue.get("risk_engine_allowed") is not False
        or rescue.get("tracking_changed") is not False
        or rescue.get("identity_inference_generated") is not False
        or rescue.get("zero_overlap_identity_verified") is not False
    ):
        raise ValueError("F4-6B research lock/contract not proven")

    selected = [
        event for event in rescue["unique_break_events"]
        if _passes_primary_gate(event)
    ]

    bundles = _load_bundles(all_batch_roots)
    if not bundles:
        raise ValueError("no archived bundles available")

    source_bundle = _read(
        source_root / "slots" / _slot_filename(
            _read(source_root / "batch_manifest.json")["slot_results"][0][
                "collection_slot_utc"
            ]
        )
    )
    reference_grid = source_bundle["components"]["radar_tracking"]["fixed_mosaic"]
    frames, edges = _build_archive_index(bundles, reference_grid)

    audits = [_audit_event(event, frames, edges) for event in selected]
    audited = [row for row in audits if row["audit_status"] == "AUDITED"]
    conflict_free = [
        row for row in audited
        if row["incoming_primary_owner_conflict"] is False
    ]

    def continuity_count(rows: list[dict], minimum_steps: int) -> int:
        return sum(
            int(row["forward_primary_continuity_steps"]) >= minimum_steps
            for row in rows
        )

    stop_reasons = Counter(
        str(row.get("forward_stop_reason"))
        for row in audited
    )

    return {
        "schema_version": "0.1.0",
        "product": "F4_MOTION_RESCUE_POSTBREAK_CONTINUITY_AUDIT",
        "research_mode": "RETROSPECTIVE_POSTBREAK_STRESS_TEST",
        "primary_gate": {
            "distance_gate_pixels": PRIMARY_DISTANCE_GATE_PIXELS,
            "minimum_top1_to_second_margin_pixels": PRIMARY_MARGIN_GATE_PIXELS,
            "gate_name": "d8_m3",
            "gate_frozen_before_postbreak_audit": True,
        },
        "zero_overlap_unique_break_count": rescue[
            "zero_overlap_unique_break_count"
        ],
        "selected_unique_break_candidate_count": len(selected),
        "audited_candidate_count": len(audited),
        "incoming_primary_owner_conflict_count": sum(
            row["incoming_primary_owner_conflict"] is True
            for row in audited
        ),
        "incoming_primary_owner_conflict_free_count": len(conflict_free),
        "forward_continuity_all_candidates": {
            "at_least_5min_count": continuity_count(audited, 1),
            "at_least_10min_count": continuity_count(audited, 2),
            "at_least_15min_count": continuity_count(audited, 3),
        },
        "forward_continuity_conflict_free_candidates": {
            "at_least_5min_count": continuity_count(conflict_free, 1),
            "at_least_10min_count": continuity_count(conflict_free, 2),
            "at_least_15min_count": continuity_count(conflict_free, 3),
        },
        "forward_stop_reason_counts": dict(sorted(stop_reasons.items())),
        "candidate_audits": audits,
        "risk_engine_allowed": False,
        "official_risk_output": False,
        "lpz_forecast_generated": False,
        "tracking_changed": False,
        "identity_inference_generated": False,
        "zero_overlap_identity_verified": False,
        "production_rescue_enabled": False,
        "interpretation": (
            "Retrospective stress test only. A motion candidate is not verified identity. "
            "An incoming primary owner is treated as an ownership conflict with the proposed "
            "rescue. Forward primary continuity after the break is supporting diagnostic "
            "evidence only and uses future archived observations, so it cannot be used as "
            "a real-time rescue feature."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument(
        "--comparison-root",
        action="append",
        default=[],
        type=Path,
    )
    parser.add_argument(
        "--batch-root",
        action="append",
        required=True,
        type=Path,
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.output.exists():
        parser.error(f"refusing overwrite: {args.output}")

    result = evaluate(
        args.source_root,
        args.comparison_root,
        args.batch_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False, indent=2, allow_nan=False)
        fp.write("\n")

    print(json.dumps({
        "selected_unique_break_candidate_count": result[
            "selected_unique_break_candidate_count"
        ],
        "incoming_primary_owner_conflict_count": result[
            "incoming_primary_owner_conflict_count"
        ],
        "incoming_primary_owner_conflict_free_count": result[
            "incoming_primary_owner_conflict_free_count"
        ],
        "forward_continuity_all_candidates": result[
            "forward_continuity_all_candidates"
        ],
        "forward_continuity_conflict_free_candidates": result[
            "forward_continuity_conflict_free_candidates"
        ],
        "forward_stop_reason_counts": result["forward_stop_reason_counts"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
