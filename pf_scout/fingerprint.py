"""Event fingerprint computation."""

import hashlib
import json


def compute_event_fingerprint(contact_id, source, signal_type, source_event_id, payload):
    """Compute a deterministic fingerprint for signal deduplication.

    Args:
        contact_id: The contact's UUID
        source: Signal source (e.g. "github")
        signal_type: Type (e.g. "github/profile")
        source_event_id: Optional external event ID
        payload: Dict payload of the signal

    Returns:
        SHA-256 hex digest string
    """
    canonical = {
        "contact_id": contact_id,
        "source": source,
        "signal_type": signal_type,
        "source_event_id": source_event_id,
        "payload_hash": hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=True).encode()
        ).hexdigest()
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()
