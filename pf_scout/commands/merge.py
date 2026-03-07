"""pf-scout merge command."""

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


def get_contact_summary(conn, contact_id: str) -> dict:
    """Get summary info for a contact."""
    identifiers = conn.execute(
        "SELECT platform, identifier_value, is_primary FROM identifiers WHERE contact_id = ?",
        (contact_id,)
    ).fetchall()

    signals_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM signals WHERE contact_id = ?", (contact_id,)
    ).fetchone()["cnt"]

    notes_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM notes WHERE contact_id = ?", (contact_id,)
    ).fetchone()["cnt"]

    return {
        "identifiers": [dict(i) for i in identifiers],
        "signals_count": signals_count,
        "notes_count": notes_count,
    }


@click.command("merge")
@click.argument("source_id")
@click.argument("target_id")
@click.option("--confirm", is_flag=True, help="Confirm merge without prompt")
@click.pass_context
def merge_cmd(ctx, source_id, target_id, confirm):
    """Merge SOURCE contact into TARGET (TARGET survives).

    Re-parents all identifiers and signals from SOURCE to TARGET,
    then archives the SOURCE contact.
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    try:
        # 1. Verify both contacts exist
        source = resolve_contact(conn, source_id)
        if not source:
            raise click.ClickException(f"Source contact not found: {source_id}")

        target = resolve_contact(conn, target_id)
        if not target:
            raise click.ClickException(f"Target contact not found: {target_id}")

        if source["id"] == target["id"]:
            raise click.ClickException("Cannot merge a contact with itself")

        # 2. Show preview
        source_summary = get_contact_summary(conn, source["id"])
        target_summary = get_contact_summary(conn, target["id"])

        click.echo("\n┌─ MERGE PREVIEW ─────────────────────────────────┐")
        click.echo("│ SOURCE (will be archived):                      │")
        click.echo(f"│   Label: {source['canonical_label']:<39}│")
        click.echo(f"│   ID: {source['id']:<42}│")
        click.echo(f"│   Identifiers: {len(source_summary['identifiers']):<33}│")
        click.echo(f"│   Signals: {source_summary['signals_count']:<37}│")
        click.echo(f"│   Notes: {source_summary['notes_count']:<39}│")
        click.echo("├──────────────────────────────────────────────────┤")
        click.echo("│ TARGET (will survive):                          │")
        click.echo(f"│   Label: {target['canonical_label']:<39}│")
        click.echo(f"│   ID: {target['id']:<42}│")
        click.echo(f"│   Identifiers: {len(target_summary['identifiers']):<33}│")
        click.echo(f"│   Signals: {target_summary['signals_count']:<37}│")
        click.echo(f"│   Notes: {target_summary['notes_count']:<39}│")
        click.echo("└──────────────────────────────────────────────────┘")

        # 3. Confirm
        if not confirm:
            if not click.confirm("\nProceed with merge?"):
                click.echo("Merge cancelled.")
                return

        now = datetime.now(timezone.utc).isoformat()

        # 4. Re-parent identifiers
        conn.execute(
            "UPDATE identifiers SET contact_id = ? WHERE contact_id = ?",
            (target["id"], source["id"])
        )

        # 5. Re-parent signals
        conn.execute(
            "UPDATE signals SET contact_id = ? WHERE contact_id = ?",
            (target["id"], source["id"])
        )

        # 6. Archive source
        conn.execute(
            "UPDATE contacts SET archived = 1, last_updated = ? WHERE id = ?",
            (now, source["id"])
        )

        # 7. Add notes to both contacts
        merge_note_source = f"Merged into {target['canonical_label']} ({target['id']})"
        merge_note_target = f"Absorbed {source['canonical_label']} ({source['id']}) — {len(source_summary['identifiers'])} identifiers, {source_summary['signals_count']} signals"

        conn.execute(
            "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) VALUES (?, ?, ?, ?, ?)",
            (source["id"], now, "system", merge_note_source, "private")
        )
        conn.execute(
            "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) VALUES (?, ?, ?, ?, ?)",
            (target["id"], now, "system", merge_note_target, "private")
        )

        # Update target's last_updated and notes_count
        conn.execute(
            "UPDATE contacts SET last_updated = ?, notes_count = notes_count + 1 WHERE id = ?",
            (now, target["id"])
        )
        conn.execute(
            "UPDATE contacts SET notes_count = notes_count + 1 WHERE id = ?",
            (source["id"],)
        )

        conn.commit()

        click.echo(f"\n✓ Merged {source['canonical_label']} → {target['canonical_label']}")
        click.echo(f"  Re-parented {len(source_summary['identifiers'])} identifiers and {source_summary['signals_count']} signals")
        click.echo("  Source contact archived")

    finally:
        conn.close()
