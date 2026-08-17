"""Domain record for the Smallink sensory data layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class SensoryRecord:
    record_id: str
    source_type: str
    connector_id: Optional[str]
    account_id: Optional[str]
    external_id: str
    content_type: str
    raw_content: str
    normalized_content: str
    occurred_at: str
    ingested_at: str
    project_path: Optional[str]
    conversation_id: Optional[str]
    content_hash: str
    sensitivity: str
    governance_status: str
    metadata: dict[str, Any]
    source_locator: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
