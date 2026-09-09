"""Scientific Evidence Engine utilities.

This module validates the curated literature registry before any paper-derived
feature is allowed to influence LPZ research or an operational risk engine.
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
}


@dataclass(frozen=True)
class EvidenceValidationResult:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    paper_count: int
    evidence_count: int
    required_variable_count: int


def load_registry(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("scientific evidence registry must be a JSON object")
    return data


def _duplicates(values: list[str]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for value in values:
        if value in seen:
            dupes.add(value)
        seen.add(value)
    return dupes


def validate_registry(data: dict[str, Any]) -> EvidenceValidationResult:
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
    if flwv:
        if flwv.get("implementation_status") == "READY_AFTER_GFS_DECODE":
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

    return EvidenceValidationResult(
        ok=not errors,
        errors=tuple(errors),
        warnings=tuple(warnings),
        paper_count=len(papers),
        evidence_count=len(evidence_items),
        required_variable_count=len(required_vars),
    )
