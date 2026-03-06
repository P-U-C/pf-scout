"""pf-scout show command."""

import json
from datetime import datetime

import click

from ..db import get_connection


def render_text_card(contact, identifiers, signals, notes, show_history=False, show_signals=False):
    """Render a terminal-friendly contact card with box-drawing characters."""
    label = contact["canonical_label"]
    cid = contact["id"]
    first_seen = contact["first_seen"]
    last_updated = contact["last_updated"]
    tags = json.loads(contact["tags"]) if contact["tags"] else []
    archived = bool(contact["archived"])

    width = 50
    inner = width - 2

    lines = []
    lines.append(f"┌{'─' * inner}┐")
    lines.append(f"│ {'Contact: ' + label:<{inner - 1}}│")
    lines.append(f"├{'─' * inner}┤")
    lines.append(f"│ {'ID: ' + cid:<{inner - 1}}│")
    lines.append(f"│ {'First seen: ' + first_seen:<{inner - 1}}│")
    lines.append(f"│ {'Last updated: ' + last_updated:<{inner - 1}}│")

    if tags:
        tag_str = ", ".join(tags)
        lines.append(f"│ {'Tags: ' + tag_str:<{inner - 1}}│")

    if archived:
        lines.append(f"│ {'Status: ARCHIVED':<{inner - 1}}│")

    # Identifiers section
    if identifiers:
        lines.append(f"├{'─' * inner}┤")
        lines.append(f"│ {'Identifiers':<{inner - 1}}│")
        for ident in identifiers:
            primary = " ★" if ident["is_primary"] else ""
            ident_str = f"  {ident['platform']}:{ident['identifier_value']}{primary}"
            conf = f" (conf={ident['link_confidence']:.2f})"
            full = ident_str + conf
            lines.append(f"│ {full:<{inner - 1}}│")

    # Signals section
    if show_signals and signals:
        lines.append(f"├{'─' * inner}┤")
        lines.append(f"│ {'Signals (' + str(len(signals)) + ')':<{inner - 1}}│")
        for sig in signals[:20]:  # Cap display at 20
            sig_str = f"  [{sig['signal_type']}] {sig['collected_at']}"
            lines.append(f"│ {sig_str:<{inner - 1}}│")
        if len(signals) > 20:
            lines.append(f"│ {'  ... and ' + str(len(signals) - 20) + ' more':<{inner - 1}}│")

    # Notes / history section
    if show_history and notes:
        lines.append(f"├{'─' * inner}┤")
        lines.append(f"│ {'Notes (' + str(len(notes)) + ')':<{inner - 1}}│")
        for note in notes[:10]:
            note_str = f"  [{note['note_ts']}] {note['body'][:30]}"
            lines.append(f"│ {note_str:<{inner - 1}}│")

    lines.append(f"└{'─' * inner}┘")
    return "\n".join(lines)


def render_json(contact, identifiers, signals, notes):
    """Render contact data as JSON."""
    data = {
        "id": contact["id"],
        "canonical_label": contact["canonical_label"],
        "first_seen": contact["first_seen"],
        "last_updated": contact["last_updated"],
        "tags": json.loads(contact["tags"]) if contact["tags"] else [],
        "notes_count": contact["notes_count"],
        "archived": bool(contact["archived"]),
        "identifiers": [
            {
                "id": i["id"],
                "platform": i["platform"],
                "identifier_value": i["identifier_value"],
                "is_primary": bool(i["is_primary"]),
                "link_confidence": i["link_confidence"],
                "link_source": i["link_source"],
            }
            for i in identifiers
        ],
        "signals_count": len(signals),
        "signals": [
            {
                "id": s["id"],
                "signal_type": s["signal_type"],
                "source": s["source"],
                "collected_at": s["collected_at"],
                "payload": json.loads(s["payload"]) if s["payload"] else {},
            }
            for s in signals
        ],
        "notes": [
            {
                "id": n["id"],
                "note_ts": n["note_ts"],
                "author": n["author"],
                "body": n["body"],
            }
            for n in notes
        ],
    }
    return json.dumps(data, indent=2)


def render_markdown(contact, identifiers, signals, notes):
    """Render contact data as Markdown."""
    lines = []
    lines.append(f"# {contact['canonical_label']}")
    lines.append(f"")
    lines.append(f"**ID:** {contact['id']}")
    lines.append(f"**First seen:** {contact['first_seen']}")
    lines.append(f"**Last updated:** {contact['last_updated']}")
    lines.append(f"")

    if identifiers:
        lines.append(f"## Identifiers")
        for i in identifiers:
            primary = " ★" if i["is_primary"] else ""
            lines.append(f"- `{i['platform']}:{i['identifier_value']}`{primary} (confidence: {i['link_confidence']})")
        lines.append(f"")

    if signals:
        lines.append(f"## Signals ({len(signals)})")
        for s in signals[:20]:
            lines.append(f"- [{s['signal_type']}] {s['collected_at']}")
        lines.append(f"")

    return "\n".join(lines)


@click.command("show")
@click.argument("identifier")
@click.option("--format", "output_format", type=click.Choice(["text", "json", "md"]),
              default="text", help="Output format")
@click.option("--history", is_flag=True, help="Show notes/history")
@click.option("--signals", "show_signals", is_flag=True, help="Show signals")
@click.pass_context
def show_command(ctx, identifier, output_format, history, show_signals):
    """Show a contact card by identifier (platform:value)."""
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

        # Fetch contact
        contact = conn.execute(
            "SELECT * FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()

        if not contact:
            raise click.ClickException(f"Contact not found for identifier: {identifier}")

        # Fetch all identifiers for this contact
        identifiers_rows = conn.execute(
            "SELECT * FROM identifiers WHERE contact_id = ? ORDER BY is_primary DESC",
            (contact_id,)
        ).fetchall()

        # Fetch signals
        signals_rows = conn.execute(
            "SELECT * FROM signals WHERE contact_id = ? ORDER BY collected_at DESC",
            (contact_id,)
        ).fetchall()

        # Fetch notes
        notes_rows = conn.execute(
            "SELECT * FROM notes WHERE contact_id = ? ORDER BY note_ts DESC",
            (contact_id,)
        ).fetchall()

        if output_format == "json":
            click.echo(render_json(contact, identifiers_rows, signals_rows, notes_rows))
        elif output_format == "md":
            click.echo(render_markdown(contact, identifiers_rows, signals_rows, notes_rows))
        else:
            click.echo(render_text_card(
                contact, identifiers_rows, signals_rows, notes_rows,
                show_history=history, show_signals=show_signals
            ))

    finally:
        conn.close()
