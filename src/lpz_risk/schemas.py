from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ProbeResult:
    source_id: str
    source_name: str
    status: str
    probe_type: str
    checked_at: str
    url: str | None = None
    http_status: int | None = None
    bytes_received: int | None = None
    latency_ms: int | None = None
    data_time: str | None = None
    data_age_seconds: int | None = None
    parse_status: str = "NOT_ATTEMPTED"
    records: int | None = None
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
