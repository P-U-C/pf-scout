"""Data models for pf-scout."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Contact:
    id: str
    canonical_label: str
    first_seen: str
    last_updated: str
    tags: str = "[]"
    notes_count: int = 0
    archived: int = 0


@dataclass
class Identifier:
    id: str
    contact_id: str
    platform: str
    identifier_value: str
    is_primary: int = 0
    first_seen: str = ""
    last_seen: str = ""
    link_confidence: float = 1.0
    link_source: Optional[str] = None


@dataclass
class Signal:
    id: Optional[int] = None
    contact_id: str = ""
    identifier_id: str = ""
    collected_at: str = ""
    signal_ts: Optional[str] = None
    source: str = ""
    signal_type: str = ""
    source_event_id: Optional[str] = None
    event_fingerprint: str = ""
    payload: str = "{}"
    evidence_note: Optional[str] = None


@dataclass
class Snapshot:
    id: Optional[int] = None
    contact_id: str = ""
    snapshot_ts: str = ""
    rubric_name: str = ""
    rubric_version: str = ""
    trigger: str = ""
    dimension_scores: str = "{}"
    total_score: float = 0.0
    weighted_score: float = 0.0
    tier: str = ""
    signals_used: str = "[]"


@dataclass
class Note:
    id: Optional[int] = None
    contact_id: str = ""
    note_ts: str = ""
    author: str = "system"
    body: str = ""
    privacy_tier: str = "private"
