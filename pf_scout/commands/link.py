"""pf-scout link command."""

import uuid
from datetime import datetime

import click

from ..db import get_connection


def parse_identifier(value: str):
    """Parse 'platform:value' into (platform, identifier_value)."""
    if ":" not in value:
        raise click.BadParameter(f"Invalid identifier format: {value}. Expected platform:value")
    platform, _, ident_value = value.partition(":")
    return platform, ident_value


def find_or_create_identifier(conn, platform, ident_value, now):
    """Find an existing identifier or create a new one with a placeholder contact."""
    row = conn.execute(
        "SELECT id, contact_id FROM identifiers WHERE platform = ? AND identifier_value = ?",
        (platform, ident_value)
    ).fetchone()

    if row:
        return row["id"], row["contact_id"]

    # Create a placeholder contact for the orphan identifier
    contact_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO contacts (id, canonical_label, first_seen, last_updated) VALUES (?, ?, ?, ?)",
        (contact_id, f"{platform}:{ident_value}", now, now)
    )
    ident_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO identifiers "
        "(id, contact_id, platform, identifier_value, is_primary, first_seen, last_seen, "
        "link_confidence, link_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ident_id, contact_id, platform, ident_value, 1, now, now, 1.0, "manual")
    )
    return ident_id, contact_id


@click.command("link")
@click.argument("ident_a")
@click.argument("ident_b")
@click.option("--confidence", type=float, default=0.95, help="Link confidence (0-1)")
@click.option("--source", "link_source", default="manual", help="Link source")
@click.pass_context
def link_command(ctx, ident_a, ident_b, confidence, link_source):
    """Link two identifiers to the same contact.

    Re-parents the second identifier to the first's contact.
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    try:
        platform_a, value_a = parse_identifier(ident_a)
        platform_b, value_b = parse_identifier(ident_b)

        id_a, contact_a = find_or_create_identifier(conn, platform_a, value_a, now)
        id_b, contact_b = find_or_create_identifier(conn, platform_b, value_b, now)

        # Re-parent B to A's contact
        conn.execute(
            "UPDATE identifiers SET contact_id = ?, link_confidence = ?, link_source = ?, "
            "last_seen = ? WHERE id = ?",
            (contact_a, confidence, link_source, now, id_b)
        )

        # Also re-parent any signals that belonged to B's contact via B's identifier
        conn.execute(
            "UPDATE signals SET contact_id = ? WHERE identifier_id = ?",
            (contact_a, id_b)
        )

        # Add system note
        conn.execute(
            "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) "
            "VALUES (?, ?, ?, ?, ?)",
            (contact_a, now, "system",
             f"Linked {ident_a} → {ident_b} ({link_source}, confidence={confidence})",
             "private")
        )

        # Update notes_count
        notes_count = conn.execute(
            "SELECT COUNT(*) FROM notes WHERE contact_id = ?", (contact_a,)
        ).fetchone()[0]
        conn.execute(
            "UPDATE contacts SET notes_count = ?, last_updated = ? WHERE id = ?",
            (notes_count, now, contact_a)
        )

        # Clean up orphan contact if different and now empty
        if contact_b != contact_a:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM identifiers WHERE contact_id = ?", (contact_b,)
            ).fetchone()[0]
            if remaining == 0:
                # Move any notes too
                conn.execute(
                    "UPDATE notes SET contact_id = ? WHERE contact_id = ?",
                    (contact_a, contact_b)
                )
                conn.execute("DELETE FROM contacts WHERE id = ?", (contact_b,))

        conn.commit()
        click.echo(f"✓ Linked {ident_a} → {ident_b} (confidence={confidence}, source={link_source})")

    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()
