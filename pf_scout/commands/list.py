"""pf-scout list command — list all contacts."""

import json

import click

from ..db import get_connection


@click.command("list")
@click.option("--include-archived", is_flag=True, help="Include archived contacts")
@click.option("--archived-only", is_flag=True, help="Show only archived contacts")
@click.option("--tag", "filter_tag", default=None, help="Filter by tag")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]),
              default="text", help="Output format")
@click.pass_context
def list_command(ctx, include_archived, archived_only, filter_tag, output_format):
    """List all contacts.

    By default, archived contacts are excluded.

    Examples:
        pf-scout list                       # list active contacts
        pf-scout list --include-archived    # list all contacts
        pf-scout list --archived-only       # list only archived
        pf-scout list --tag infra           # filter by tag
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    try:
        # Build query
        if archived_only:
            query = "SELECT * FROM contacts WHERE archived = 1"
        elif include_archived:
            query = "SELECT * FROM contacts"
        else:
            query = "SELECT * FROM contacts WHERE archived = 0"

        query += " ORDER BY last_updated DESC"

        contacts = conn.execute(query).fetchall()

        # Filter by tag if specified
        if filter_tag:
            filtered = []
            for c in contacts:
                tags = json.loads(c["tags"]) if c["tags"] else []
                if filter_tag in tags:
                    filtered.append(c)
            contacts = filtered

        if output_format == "json":
            data = []
            for c in contacts:
                # Get primary identifier
                ident = conn.execute(
                    "SELECT platform, identifier_value FROM identifiers "
                    "WHERE contact_id = ? ORDER BY is_primary DESC LIMIT 1",
                    (c["id"],)
                ).fetchone()

                data.append({
                    "id": c["id"],
                    "canonical_label": c["canonical_label"],
                    "primary_identifier": f"{ident['platform']}:{ident['identifier_value']}" if ident else None,
                    "tags": json.loads(c["tags"]) if c["tags"] else [],
                    "notes_count": c["notes_count"],
                    "archived": bool(c["archived"]),
                    "first_seen": c["first_seen"],
                    "last_updated": c["last_updated"],
                })
            click.echo(json.dumps(data, indent=2))
        else:
            # Text table output
            if not contacts:
                click.echo("No contacts found.")
                return

            click.echo(f"{'Label':<30} {'Identifier':<25} {'Tags':<20} {'Status':<10}")
            click.echo("─" * 85)

            for c in contacts:
                # Get primary identifier
                ident = conn.execute(
                    "SELECT platform, identifier_value FROM identifiers "
                    "WHERE contact_id = ? ORDER BY is_primary DESC LIMIT 1",
                    (c["id"],)
                ).fetchone()

                ident_str = f"{ident['platform']}:{ident['identifier_value']}" if ident else "-"
                if len(ident_str) > 23:
                    ident_str = ident_str[:20] + "..."

                tags = json.loads(c["tags"]) if c["tags"] else []
                tag_str = ", ".join(tags[:3])
                if len(tags) > 3:
                    tag_str += "..."
                if len(tag_str) > 18:
                    tag_str = tag_str[:15] + "..."

                label = c["canonical_label"]
                if len(label) > 28:
                    label = label[:25] + "..."

                status = "ARCHIVED" if c["archived"] else "active"

                click.echo(f"{label:<30} {ident_str:<25} {tag_str:<20} {status:<10}")

            click.echo("─" * 85)
            click.echo(f"Total: {len(contacts)} contacts")

    finally:
        conn.close()
