"""pf-scout archive command."""

from datetime import datetime, timezone

import click

from ..db import get_connection


def resolve_contact(conn, identifier: str) -> dict:
    """Resolve an identifier (platform:value or contact ID) to a contact dict."""
    # First try direct contact ID
    row = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (identifier,)
    ).fetchone()
    if row:
        return dict(row)

    # Try platform:value format
    if ":" in identifier:
        platform, _, value = identifier.partition(":")
        ident_row = conn.execute(
            "SELECT contact_id FROM identifiers WHERE platform = ? AND identifier_value = ?",
            (platform, value)
        ).fetchone()
        if ident_row:
            row = conn.execute(
                "SELECT * FROM contacts WHERE id = ?", (ident_row["contact_id"],)
            ).fetchone()
            if row:
                return dict(row)

    return None


@click.command("archive")
@click.argument("identifier")
@click.option("--restore", is_flag=True, help="Restore an archived contact")
@click.option("--reason", default=None, help="Reason for archiving (added as note)")
@click.pass_context
def archive_cmd(ctx, identifier, restore, reason):
    """Archive or restore a contact.

    Archived contacts are hidden from default listings but data is preserved.

    Examples:
        pf-scout archive twitter:alice --reason "No longer active"
        pf-scout archive twitter:alice --restore
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    try:
        # Resolve identifier to contact
        contact = resolve_contact(conn, identifier)
        if not contact:
            raise click.ClickException(f"Contact not found: {identifier}")

        now = datetime.now(timezone.utc).isoformat()
        label = contact["canonical_label"]

        if restore:
            # Restore (unarchive)
            if not contact["archived"]:
                click.echo(f"{label} is not archived")
                return

            conn.execute(
                "UPDATE contacts SET archived = 0, last_updated = ? WHERE id = ?",
                (now, contact["id"])
            )

            # Add restore note
            conn.execute(
                "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) VALUES (?, ?, ?, ?, ?)",
                (contact["id"], now, "system", "Contact restored from archive", "private")
            )
            conn.execute(
                "UPDATE contacts SET notes_count = notes_count + 1 WHERE id = ?",
                (contact["id"],)
            )

            conn.commit()
            click.echo(f"✓ Restored {label}")

        else:
            # Archive
            if contact["archived"]:
                click.echo(f"{label} is already archived")
                return

            conn.execute(
                "UPDATE contacts SET archived = 1, last_updated = ? WHERE id = ?",
                (now, contact["id"])
            )

            # Add archive note with optional reason
            note_body = "Contact archived"
            if reason:
                note_body = f"Contact archived: {reason}"

            conn.execute(
                "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) VALUES (?, ?, ?, ?, ?)",
                (contact["id"], now, "system", note_body, "private")
            )
            conn.execute(
                "UPDATE contacts SET notes_count = notes_count + 1 WHERE id = ?",
                (contact["id"],)
            )

            conn.commit()
            click.echo(f"✓ Archived {label}")
            if reason:
                click.echo(f"  Reason: {reason}")

    finally:
        conn.close()
