"""pf-scout export command — export all contact data."""

import hashlib
import json
from datetime import datetime

import click

from ..db import get_connection


def anonymize_value(value: str, salt: str = "") -> str:
    """Create a deterministic anonymous identifier."""
    h = hashlib.sha256((salt + value).encode()).hexdigest()[:12]
    return f"anon_{h}"


@click.command("export")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="Output file path (defaults to stdout)")
@click.option("--anonymize", is_flag=True,
              help="Redact personal identifiers")
@click.option("--include-private", is_flag=True,
              help="Include private notes in export")
@click.pass_context
def export_command(ctx, output_path, anonymize, include_private):
    """Export all contact data to JSON.

    Exports contacts, identifiers, signals, snapshots, and notes.
    Use --anonymize to redact personal identifiers for sharing.
    Use --include-private to include private notes (excluded by default).
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    # Salt for anonymization (use db path as deterministic salt)
    anon_salt = db_path if anonymize else ""

    try:
        export_data = {
            "exported_at": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            "anonymized": anonymize,
            "include_private_notes": include_private,
            "contacts": [],
        }

        # Fetch all contacts
        contacts = conn.execute(
            "SELECT * FROM contacts WHERE archived = 0 ORDER BY canonical_label"
        ).fetchall()

        for contact in contacts:
            contact_id = contact["id"]

            # Get identifiers
            identifiers = conn.execute(
                "SELECT * FROM identifiers WHERE contact_id = ?",
                (contact_id,)
            ).fetchall()

            # Get signals
            signals = conn.execute(
                "SELECT * FROM signals WHERE contact_id = ? ORDER BY collected_at DESC",
                (contact_id,)
            ).fetchall()

            # Get snapshots
            snapshots = conn.execute(
                "SELECT * FROM snapshots WHERE contact_id = ? ORDER BY snapshot_ts DESC",
                (contact_id,)
            ).fetchall()

            # Get notes (filter private unless --include-private)
            notes_query = "SELECT * FROM notes WHERE contact_id = ?"
            if not include_private:
                notes_query += " AND privacy_tier != 'private'"
            notes_query += " ORDER BY note_ts DESC"
            notes = conn.execute(notes_query, (contact_id,)).fetchall()

            # Build contact export
            contact_export = {
                "id": anonymize_value(contact_id, anon_salt) if anonymize else contact_id,
                "canonical_label": anonymize_value(contact["canonical_label"], anon_salt) if anonymize else contact["canonical_label"],
                "first_seen": contact["first_seen"],
                "last_updated": contact["last_updated"],
                "tags": json.loads(contact["tags"]) if contact["tags"] else [],
                "notes_count": contact["notes_count"],
                "identifiers": [],
                "signals": [],
                "snapshots": [],
                "notes": [],
            }

            # Export identifiers
            for ident in identifiers:
                ident_value = ident["identifier_value"]
                if anonymize:
                    ident_value = anonymize_value(ident_value, anon_salt)

                contact_export["identifiers"].append({
                    "id": anonymize_value(ident["id"], anon_salt) if anonymize else ident["id"],
                    "platform": ident["platform"],
                    "identifier_value": ident_value,
                    "is_primary": bool(ident["is_primary"]),
                    "link_confidence": ident["link_confidence"],
                    "link_source": ident["link_source"],
                    "first_seen": ident["first_seen"],
                    "last_seen": ident["last_seen"],
                })

            # Export signals
            for sig in signals:
                payload = json.loads(sig["payload"]) if sig["payload"] else {}

                # Anonymize payload if needed
                if anonymize and payload:
                    # Redact common PII fields
                    for key in ["username", "login", "email", "name", "author", "user"]:
                        if key in payload:
                            payload[key] = anonymize_value(str(payload[key]), anon_salt)

                contact_export["signals"].append({
                    "id": sig["id"],
                    "signal_type": sig["signal_type"],
                    "source": sig["source"],
                    "collected_at": sig["collected_at"],
                    "signal_ts": sig["signal_ts"],
                    "payload": payload,
                    "evidence_note": sig["evidence_note"],
                })

            # Export snapshots
            for snap in snapshots:
                contact_export["snapshots"].append({
                    "id": snap["id"],
                    "snapshot_ts": snap["snapshot_ts"],
                    "rubric_name": snap["rubric_name"],
                    "rubric_version": snap["rubric_version"],
                    "trigger": snap["trigger"],
                    "dimension_scores": json.loads(snap["dimension_scores"]) if snap["dimension_scores"] else {},
                    "total_score": snap["total_score"],
                    "weighted_score": snap["weighted_score"],
                    "tier": snap["tier"],
                })

            # Export notes
            for note in notes:
                note_body = note["body"]
                if anonymize:
                    # Simple anonymization — replace potential names/handles
                    note_body = "[redacted note content]"

                contact_export["notes"].append({
                    "id": note["id"],
                    "note_ts": note["note_ts"],
                    "author": anonymize_value(note["author"], anon_salt) if anonymize else note["author"],
                    "body": note_body,
                    "privacy_tier": note["privacy_tier"],
                })

            export_data["contacts"].append(contact_export)

        # Summary stats
        export_data["summary"] = {
            "total_contacts": len(export_data["contacts"]),
            "total_signals": sum(len(c["signals"]) for c in export_data["contacts"]),
            "total_snapshots": sum(len(c["snapshots"]) for c in export_data["contacts"]),
            "total_notes": sum(len(c["notes"]) for c in export_data["contacts"]),
        }

        # Output
        json_output = json.dumps(export_data, indent=2)

        if output_path:
            with open(output_path, "w") as f:
                f.write(json_output)
            click.echo(f"✓ Exported {len(export_data['contacts'])} contacts to {output_path}")
        else:
            click.echo(json_output)

    finally:
        conn.close()
