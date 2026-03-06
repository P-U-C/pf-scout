"""Base collector interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Tuple, Optional

SIGNAL_REGISTRY = {
    "github/profile": {
        "source": "github",
        "idempotent": True,
        "redaction_fields": ["email"],
        "description": "GitHub user profile snapshot",
    },
    "github/repo_stats": {
        "source": "github",
        "idempotent": True,
        "redaction_fields": [],
        "description": "GitHub repository statistics for a user",
    },
    "postfiat/context": {
        "source": "postfiat",
        "idempotent": False,
        "redaction_fields": [],
        "description": "PF Context document — user's stated Value, Strategy, Tactics",
    },
}


@dataclass
class CollectedSignal:
    """A signal produced by a collector, ready for DB insertion."""
    source: str
    signal_type: str
    payload: dict
    source_event_id: Optional[str] = None
    signal_ts: Optional[str] = None
    evidence_note: Optional[str] = None


class BaseCollector(ABC):
    """Abstract base class for signal collectors."""

    @abstractmethod
    def discover(self, target: str, token: Optional[str] = None) -> List[Tuple[str, str]]:
        """Discover identifiers from a target (e.g. org name).

        Returns:
            List of (platform, identifier_value) tuples
        """
        pass

    @abstractmethod
    def collect(self, identifier_value: str, contact_id: str,
                token: Optional[str] = None) -> List[CollectedSignal]:
        """Collect signals for a given identifier.

        Returns:
            List of CollectedSignal objects
        """
        pass
