"""Scientific Evidence Engine utilities.

This module validates the curated literature registry and the derived scientific
variable requirements before any paper-derived feature is allowed to influence
LPZ research or an operational risk engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_EVIDENCE_LEVELS = {
    "PEER_REVIEWED_PRIMARY",
    "PEER_REVIEWED_REVIEW",
    "OFFICIAL_TECHNICAL",
}

ALLOWED_IMPLEMENTATION_PREFIXES = {
    "READY",
    "PENDING",
    "BLOCKED",
    "RESEARCH_ONLY",
    "EXACT",
}

ALLOWED_REQUIREMENT_PREFIXES = {
    "EXACT",
    "PENDING",
    "BLOCKED",
}


@dataclass(frozen=True)
class EvidenceValidationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    paper_count: int
    evidence_count: int
    required_variable_count: int
    requirement_count: int = 0


def load_json_object(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_registry(path: str | Path) -> dict[str, Any]:
    return load_json_object(path)


def load_variable_requirements(path: str | Path) -> dict[str, Any]:
    return load_json_object(path)


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return dupes


def _validate_registry_core(data: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []

    papers = data.get("papers", [])
    evidence_items = data.get("evidence_items", [])
    required_vars = data.get("required_variable_registry", [])

    if not isinstance(papers, list) or not papers:
        errors.append("papers must be a non-empty list")
        papers = []
    if not isinstance(evidence_items, list) or not evidence_items:
        errors.append("evidence_items must be a non-empty list")
        evidence_items = []
    if not isinstance(required_vars, list):
        errors.append("required_variable_registry must be a list")
        required_vars = []

    paper_ids = [str(p.get("paper_id", "")) for p in papers if isinstance(p, dict)]
    evidence_ids = [str(e.get("evidence_id", "")) for e in evidence_items if isinstance(e, dict)]

    for duplicate in sorted(_duplicates(paper_ids)):
        errors.append(f"duplicate paper_id: {duplicate}")
    for duplicate in sorted(_duplicates(evidence_ids)):
        errors.append(f"duplicate evidence_id: {duplicate}")

    valid_paper_ids = set(paper_ids)
    valid_evidence_ids = set(evidence_ids)

    for idx, paper in enumerate(papers):
        if not isinstance(paper, dict):
            errors.append(f"papers[{idx}] must be an object")
            continue
        for field in ("paper_id", "year", "title", "authors", "doi", "scope", "evidence_level"):
            if not paper.get(field):
                errors.append(f"{paper.get('paper_id', idx)} missing paper field: {field}")
        if paper.get("evidence_level") not in ALLOWED_EVIDENCE_LEVELS:
            errors.append(
                f"{paper.get('paper_id', idx)} unsupported evidence_level: "
                f"{paper.get('evidence_level')}"
            )

    for idx, item in enumerate(evidence_items):
        if not isinstance(item, dict):
            errors.append(f"evidence_items[{idx}] must be an object")
            continue
        evidence_id = str(item.get("evidence_id", f"index-{idx}"))
        paper_id = item.get("paper_id")
        if not item.get("evidence_id"):
            errors.append(f"evidence_items[{idx}] missing evidence_id")
        if paper_id not in valid_paper_ids:
            errors.append(f"{evidence_id} references unknown paper_id: {paper_id}")
        if not item.get("kind"):
            errors.append(f"{evidence_id} missing kind")
        if not item.get("feature_id"):
            errors.append(f"{evidence_id} missing feature_id")

        status = str(item.get("implementation_status", ""))
        if not any(status.startswith(prefix) for prefix in ALLOWED_IMPLEMENTATION_PREFIXES):
            errors.append(f"{evidence_id} invalid implementation_status: {status}")

        if item.get("threshold") and item.get("kind") not in {
            "FEATURE_THRESHOLD",
            "REGIONAL_THRESHOLD",
        }:
            warnings.append(
                f"{evidence_id} has threshold data but kind={item.get('kind')}; review semantics"
            )

    canonical_names: list[str] = []
    for idx, row in enumerate(required_vars):
        if not isinstance(row, dict):
            errors.append(f"required_variable_registry[{idx}] must be an object")
            continue
        name = str(row.get("canonical_variable", ""))
        if not name:
            errors.append(f"required_variable_registry[{idx}] missing canonical_variable")
            continue
        canonical_names.append(name)
        refs = row.get("evidence_ids", [])
        if not isinstance(refs, list) or not refs:
            errors.append(f"{name} must reference at least one evidence_id")
            continue
        unknown = sorted(set(map(str, refs)) - valid_evidence_ids)
        if unknown:
            errors.append(f"{name} references unknown evidence_ids: {unknown}")

    for duplicate in sorted(_duplicates(canonical_names)):
        errors.append(f"duplicate canonical_variable: {duplicate}")

    # Critical scientific guardrails.
    flwv = next(
        (e for e in evidence_items if isinstance(e, dict) and e.get("evidence_id") == "KATO2020_FLWV500"),
        None,
    )
    if flwv and str(flwv.get("implementation_status", "")).startswith("READY"):
        errors.append(
            "KATO2020_FLWV500 cannot be marked exact-ready from pressure-level GFS alone; "
            "the paper defines the diagnostic at 500 m height"
        )

    six_condition = next(
        (
            e
            for e in evidence_items
            if isinstance(e, dict) and e.get("evidence_id") == "TAHARA2026_SIX_CONDITION_COVERAGE"
        ),
        None,
    )
    if six_condition and six_condition.get("implementation_status") != "RESEARCH_ONLY":
        errors.append(
            "TAHARA2026_SIX_CONDITION_COVERAGE must remain research-only; "
            "the six conditions are not a deterministic all-six gate"
        )

    return errors, warnings, papers, evidence_items, required_vars


def _validate_variable_requirements(
    requirements_data: dict[str, Any],
    valid_evidence_ids: set[str],
) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []
    rows = requirements_data.get("requirements", [])

    if not isinstance(rows, list) or not rows:
        return ["scientific variable requirements must be a non-empty list"], warnings, 0

    requirement_ids: list[str] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"requirements[{idx}] must be an object")
            continue

        requirement_id = str(row.get("requirement_id", ""))
        if not requirement_id:
            errors.append(f"requirements[{idx}] missing requirement_id")
            continue
        requirement_ids.append(requirement_id)

        refs = row.get("evidence_ids", [])
        if not isinstance(refs, list) or not refs:
            errors.append(f"{requirement_id} must reference at least one evidence_id")
        else:
            unknown = sorted(set(map(str, refs)) - valid_evidence_ids)
            if unknown:
                errors.append(f"{requirement_id} references unknown evidence_ids: {unknown}")

        upstream = row.get("upstream_parameters", [])
        outputs = row.get("canonical_outputs", [])
        if not isinstance(upstream, list) or not upstream:
            errors.append(f"{requirement_id} missing upstream_parameters")
        if not isinstance(outputs, list) or not outputs:
            errors.append(f"{requirement_id} missing canonical_outputs")

        status = str(row.get("reproduction_status", ""))
        if not any(status.startswith(prefix) for prefix in ALLOWED_REQUIREMENT_PREFIXES):
            errors.append(f"{requirement_id} invalid reproduction_status: {status}")

    for duplicate in sorted(_duplicates(requirement_ids)):
        errors.append(f"duplicate requirement_id: {duplicate}")

    by_id = {
        str(row.get("requirement_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("requirement_id")
    }

    # Exact-reproduction guardrails.
    flwv = by_id.get("REQ_KATO_FLWV500")
    if flwv and not str(flwv.get("reproduction_status", "")).startswith("BLOCKED"):
        errors.append(
            "REQ_KATO_FLWV500 must remain BLOCKED until a validated 500 m AGL reconstruction exists"
        )

    ascent = by_id.get("REQ_ASCENT_700")
    if ascent and str(ascent.get("reproduction_status", "")).startswith("EXACT"):
        errors.append(
            "REQ_ASCENT_700 cannot be exact-ready while GFS VVEL omega-to-geometric-w conversion remains unresolved"
        )

    sreh = by_id.get("REQ_SREH03")
    if sreh:
        upstream = set(map(str, sreh.get("upstream_parameters", [])))
        if "HLCY" in upstream:
            errors.append(
                "REQ_SREH03 must not use precomputed HLCY as an assumed exact substitute for the Kato storm-motion method"
            )
        if str(sreh.get("reproduction_status", "")).startswith("EXACT"):
            errors.append(
                "REQ_SREH03 cannot be exact-ready before Maddox/Bunkers storm-motion reproduction is validated"
            )

    iwvf = by_id.get("REQ_IWVF_1000_900")
    if iwvf:
        levels = set(iwvf.get("levels_hpa", []))
        expected = {1000, 975, 950, 925, 900}
        if not expected.issubset(levels):
            errors.append(
                "REQ_IWVF_1000_900 must retain all available GFS pressure levels 1000/975/950/925/900 hPa"
            )

    source = requirements_data.get("source")
    if source != "NOAA_NCEP_GFS_0P25":
        warnings.append(f"unexpected Phase 1B source identifier: {source}")

    return errors, warnings, len(rows)


def validate_registry(
    data: dict[str, Any],
    requirements_data: dict[str, Any] | None = None,
) -> EvidenceValidationResult:
    errors, warnings, papers, evidence_items, required_vars = _validate_registry_core(data)

    requirement_count = 0
    if requirements_data is not None:
        valid_evidence_ids = {
            str(item.get("evidence_id"))
            for item in evidence_items
            if isinstance(item, dict) and item.get("evidence_id")
        }
        req_errors, req_warnings, requirement_count = _validate_variable_requirements(
            requirements_data,
            valid_evidence_ids,
        )
        errors.extend(req_errors)
        warnings.extend(req_warnings)

    return EvidenceValidationResult(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        paper_count=len(papers),
        evidence_count=len(evidence_items),
        required_variable_count=len(required_vars),
        requirement_count=requirement_count,
    )
