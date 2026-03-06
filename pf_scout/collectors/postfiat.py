"""PostFiat context collector.

Fetches the /context markdown document for each PF-identified contact.
Content-addressed dedup: source_event_id = SHA256 of raw markdown.
A new signal is only created when the document changes.
"""
import hashlib
import re
import time
import requests

from .base import BaseCollector, CollectedSignal


class PostFiatCollector(BaseCollector):
    name = "postfiat"
    idempotent = False  # content-addressed, but we check for changes each run

    def collect(self, identifier_value, contact_id, token=None, **kwargs):
        """Fetch /context for this PF wallet/handle."""
        cookie = kwargs.get("pf_session") or ""
        base_url = kwargs.get("base_url", "https://tasknode.postfiat.org")

        if not cookie:
            return []  # auth required, fail gracefully

        wallet = identifier_value
        signals = []

        # Try prospect context endpoint
        try:
            resp = requests.get(
                f"{base_url}/context",
                params={"user": wallet},
                headers={
                    "Cookie": cookie,
                    "User-Agent": "pf-scout/0.1.0",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                raw_markdown = resp.text
                content_hash = hashlib.sha256(raw_markdown.encode()).hexdigest()

                # Parse sections (best-effort)
                sections = _parse_context_sections(raw_markdown)

                # raw_markdown stored as-is for fidelity. If ever rendered in a web UI,
                # sanitize before display (strip script tags, etc.). CLI display is safe.
                payload = {
                    "raw_markdown": raw_markdown,
                    "version_ts": _now_utc(),
                    "word_count": len(raw_markdown.split()),
                    "section_value": sections.get("value", ""),
                    "section_strategy": sections.get("strategy", ""),
                    "section_tactics": sections.get("tactics", ""),
                }

                signals.append(CollectedSignal(
                    source="postfiat",
                    signal_type="postfiat/context",
                    source_event_id=content_hash,  # content-addressed
                    payload=payload,
                    signal_ts=_now_utc(),
                    evidence_note=f"PF Context ({len(raw_markdown.split())} words)",
                ))
            elif resp.status_code in (401, 403):
                signals.append(CollectedSignal(
                    source="postfiat",
                    signal_type="postfiat/context",
                    source_event_id="auth_required",
                    payload={"raw_markdown": None, "auth_required": True},
                    signal_ts=_now_utc(),
                    evidence_note="PF Context: requires authentication",
                ))
        except requests.RequestException:
            pass  # network failure — skip silently

        time.sleep(0.3)
        return signals

    def discover(self, target, token=None, **kwargs):
        """Discover PF wallets from leaderboard."""
        cookie = kwargs.get("pf_session", "") or token or ""
        base_url = kwargs.get("base_url", "https://tasknode.postfiat.org")
        if not cookie:
            return []

        try:
            resp = requests.get(
                f"{base_url}/leaderboard",
                headers={"Cookie": cookie, "User-Agent": "pf-scout/0.1.0"},
                timeout=10,
            )
            if resp.status_code == 200:
                # Parse wallet addresses from leaderboard response
                # Format TBD — return empty list if parsing fails
                return []
        except requests.RequestException:
            pass
        return []


def _parse_context_sections(markdown: str) -> dict:
    """Extract Value, Strategy, Tactics sections from PF Context markdown."""
    sections = {}
    current_section = None
    current_lines = []

    for line in markdown.split("\n"):
        # Match headings like ## Value, ## Strategy, ## Tactics
        heading_match = re.match(r"^#{1,3}\s+(.*)", line)
        if heading_match:
            if current_section and current_lines:
                sections[current_section] = "\n".join(current_lines).strip()
            heading = heading_match.group(1).strip().lower()
            if "value" in heading:
                current_section = "value"
            elif "strategy" in heading:
                current_section = "strategy"
            elif "tactic" in heading:
                current_section = "tactics"
            else:
                current_section = heading.replace(" ", "_")
            current_lines = []
        elif current_section:
            current_lines.append(line)

    if current_section and current_lines:
        sections[current_section] = "\n".join(current_lines).strip()

    return sections


def _now_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
