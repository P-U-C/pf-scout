"""pf-scout tag command."""

import json
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


@click.command("tag")
@click.argument("identifier")
@click.argument("tags", nargs=-1)
@click.option("--remove", is_flag=True, help="Remove the specified tags")
@click.option("--clear", is_flag=True, help="Clear all tags")
@click.pass_context
def tag_cmd(ctx, identifier, tags, remove, clear):
    """Add or remove tags from a contact.

    IDENTIFIER can be a contact ID or platform:value format.

    Examples:
        pf-scout tag twitter:alice vip priority
        pf-scout tag twitter:alice --remove vip
        pf-scout tag twitter:alice --clear
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    try:
        # Resolve identifier to contact
        contact = resolve_contact(conn, identifier)
        if not contact:
            raise click.ClickException(f"Contact not found: {identifier}")

        # Load current tags
        current_tags = json.loads(contact["tags"]) if contact["tags"] else []
        original_tags = current_tags.copy()

        now = datetime.now(timezone.utc).isoformat()

        if clear:
            # Clear all tags
            current_tags = []
            click.echo(f"Cleared all tags from {contact['canonical_label']}")
        elif remove:
            # Remove specified tags
            if not tags:
                raise click.ClickException("Specify tags to remove")
            removed = []
            for tag in tags:
                if tag in current_tags:
                    current_tags.remove(tag)
                    removed.append(tag)
            if removed:
                click.echo(f"Removed tags from {contact['canonical_label']}: {', '.join(removed)}")
            else:
                click.echo("No matching tags to remove")
        else:
            # Add tags
            if not tags:
                # Just show current tags
                if current_tags:
                    click.echo(f"Tags for {contact['canonical_label']}: {', '.join(current_tags)}")
                else:
                    click.echo(f"No tags for {contact['canonical_label']}")
                return

            added = []
            for tag in tags:
                if tag not in current_tags:
                    current_tags.append(tag)
                    added.append(tag)
            if added:
                click.echo(f"Added tags to {contact['canonical_label']}: {', '.join(added)}")
            else:
                click.echo("Tags already present")

        # Save if changed
        if current_tags != original_tags:
            conn.execute(
                "UPDATE contacts SET tags = ?, last_updated = ? WHERE id = ?",
                (json.dumps(current_tags), now, contact["id"])
            )
            conn.commit()

        # Show final state
        if current_tags:
            click.echo(f"Current tags: {', '.join(current_tags)}")
        else:
            click.echo("Current tags: (none)")

    finally:
        conn.close()
