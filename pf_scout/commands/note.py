"""pf-scout note command — add notes to contacts."""

from datetime import datetime

import click

from ..db import get_connection


@click.command("note")
@click.argument("identifier")
@click.argument("text")
@click.option("--private", is_flag=True,
              help="Mark note as private (excluded from non-private exports)")
@click.option("--author", default="user",
              help="Author identifier for the note")
@click.pass_context
def note_command(ctx, identifier, text, private, author):
    """Add a note to a contact.

    IDENTIFIER should be in platform:value format (e.g., github:username).
    TEXT is the note content.

    Examples:
        pf-scout note github:alice "Great contributor, very responsive"
        pf-scout note github:bob "Sensitive info here" --private
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    try:
        if ":" not in identifier:
            raise click.ClickException("Identifier must be in platform:value format")

        platform, _, value = identifier.partition(":")

        # Find the identifier
        ident_row = conn.execute(
            "SELECT * FROM identifiers WHERE platform = ? AND identifier_value = ?",
            (platform, value)
        ).fetchone()

        if not ident_row:
            raise click.ClickException(f"Identifier not found: {identifier}")

        contact_id = ident_row["contact_id"]

        # Get contact for display
        contact = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()

        if not contact:
            raise click.ClickException(f"Contact not found for identifier: {identifier}")

        # Create the note
        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        privacy_tier = "private" if private else "public"

        conn.execute(
            "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) "
            "VALUES (?, ?, ?, ?, ?)",
            (contact_id, now, author, text, privacy_tier)
        )

        # Update notes_count on contact
        conn.execute(
            "UPDATE contacts SET notes_count = notes_count + 1, last_updated = ? WHERE id = ?",
            (now, contact_id)
        )

        conn.commit()

        privacy_label = " [private]" if private else ""
        click.echo(f"✓ Note added to {contact['canonical_label']}{privacy_label}")

    except click.ClickException:
        raise
    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()
