"""pf-scout add command."""

import json
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


@click.command("add")
@click.argument("label")
@click.option("--identifier", "-i", "identifiers", multiple=True, required=True,
              help="Identifier in platform:value format (e.g. github:allenday)")
@click.pass_context
def add_command(ctx, label, identifiers):
    """Add a new contact with one or more identifiers."""
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    contact_id = str(uuid.uuid4())

    try:
        conn.execute(
            "INSERT INTO contacts (id, canonical_label, first_seen, last_updated) "
            "VALUES (?, ?, ?, ?)",
            (contact_id, label, now, now)
        )

        parsed = []
        for i, ident_str in enumerate(identifiers):
            platform, ident_value = parse_identifier(ident_str)
            ident_id = str(uuid.uuid4())
            is_primary = 1 if i == 0 else 0

            conn.execute(
                "INSERT INTO identifiers "
                "(id, contact_id, platform, identifier_value, is_primary, first_seen, last_seen, "
                "link_confidence, link_source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ident_id, contact_id, platform, ident_value, is_primary, now, now, 1.0, "manual")
            )
            parsed.append((platform, ident_value))

        conn.commit()

        # Print contact card
        click.echo(f"┌─────────────────────────────────────────┐")
        click.echo(f"│ Contact: {label:<31}│")
        click.echo(f"├─────────────────────────────────────────┤")
        click.echo(f"│ ID: {contact_id:<36}│")
        click.echo(f"│ First seen: {now:<28}│")
        for platform, value in parsed:
            ident_str = f"{platform}:{value}"
            click.echo(f"│ → {ident_str:<37}│")
        click.echo(f"└─────────────────────────────────────────┘")

    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()
