"""pf-scout merge command — merge two contacts (A into B, B survives)."""

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


def get_merge_preview(conn, contact_a_id: str, contact_b_id: str):
    """Generate preview of what will happen during merge."""
    # Get identifiers to move
    idents_a = conn.execute(
        "SELECT platform, identifier_value FROM identifiers WHERE contact_id = ?",
        (contact_a_id,)
    ).fetchall()

    idents_b = conn.execute(
        "SELECT platform, identifier_value FROM identifiers WHERE contact_id = ?",
        (contact_b_id,)
    ).fetchall()

    # Get signals to move
    signals_a = conn.execute(
        "SELECT COUNT(*) as cnt FROM signals WHERE contact_id = ?",
        (contact_a_id,)
    ).fetchone()["cnt"]

    signals_b = conn.execute(
        "SELECT COUNT(*) as cnt FROM signals WHERE contact_id = ?",
        (contact_b_id,)
    ).fetchone()["cnt"]

    # Get notes to move
    notes_a = conn.execute(
        "SELECT COUNT(*) as cnt FROM notes WHERE contact_id = ?",
        (contact_a_id,)
    ).fetchone()["cnt"]

    notes_b = conn.execute(
        "SELECT COUNT(*) as cnt FROM notes WHERE contact_id = ?",
        (contact_b_id,)
    ).fetchone()["cnt"]

    return {
        "identifiers_a": [(r["platform"], r["identifier_value"]) for r in idents_a],
        "identifiers_b": [(r["platform"], r["identifier_value"]) for r in idents_b],
        "signals_a": signals_a,
        "signals_b": signals_b,
        "notes_a": notes_a,
        "notes_b": notes_b,
    }


def execute_merge(conn, contact_a_id: str, contact_b_id: str, label_a: str, label_b: str):
    """Execute the merge: A → B (B survives, A archived)."""
    now = datetime.now(timezone.utc).isoformat()

    # 1. Re-parent all of A's identifiers to B
    conn.execute(
        "UPDATE identifiers SET contact_id = ? WHERE contact_id = ?",
        (contact_b_id, contact_a_id)
    )

    # 2. Re-parent all of A's signals to B
    conn.execute(
        "UPDATE signals SET contact_id = ? WHERE contact_id = ?",
        (contact_b_id, contact_a_id)
    )

    # 3. Re-parent all of A's notes to B (except keep merge note on A)
    conn.execute(
        "UPDATE notes SET contact_id = ? WHERE contact_id = ?",
        (contact_b_id, contact_a_id)
    )

    # 4. Set A's archived = 1
    conn.execute(
        "UPDATE contacts SET archived = 1, last_updated = ? WHERE id = ?",
        (now, contact_a_id)
    )

    # 5. Add system note to A: "merged_into: <B contact_id>"
    conn.execute(
        "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) VALUES (?, ?, ?, ?, ?)",
        (contact_a_id, now, "system", f"merged_into: {contact_b_id}", "private")
    )

    # 6. Add system note to B: "merged_from: <A contact_id>"
    conn.execute(
        "INSERT INTO notes (contact_id, note_ts, author, body, privacy_tier) VALUES (?, ?, ?, ?, ?)",
        (contact_b_id, now, "system", f"merged_from: {contact_a_id} ({label_a})", "private")
    )

    # 7. Update notes_count for both contacts
    notes_a = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE contact_id = ?", (contact_a_id,)
    ).fetchone()[0]
    notes_b = conn.execute(
        "SELECT COUNT(*) FROM notes WHERE contact_id = ?", (contact_b_id,)
    ).fetchone()[0]

    conn.execute(
        "UPDATE contacts SET notes_count = ?, last_updated = ? WHERE id = ?",
        (notes_a, now, contact_a_id)
    )
    conn.execute(
        "UPDATE contacts SET notes_count = ?, last_updated = ? WHERE id = ?",
        (notes_b, now, contact_b_id)
    )

    conn.commit()


@click.command("merge")
@click.argument("contact_a")
@click.argument("contact_b")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def merge_cmd(ctx, contact_a, contact_b, confirm):
    """Merge contact A into contact B (B survives, A archived).

    CONTACT_A and CONTACT_B are identifiers in platform:value format.

    Per SPEC §4.1, this will:
    - Move all of A's identifiers to B
    - Move all of A's signals to B
    - Move all of A's notes to B
    - Archive contact A
    - Add audit notes to both contacts

    Example:
        pf-scout merge github:olduser github:mainuser --confirm
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    try:
        # Resolve both contacts
        contact_a_obj = resolve_contact(conn, contact_a)
        if not contact_a_obj:
            raise click.ClickException(f"Contact A not found: {contact_a}")

        contact_b_obj = resolve_contact(conn, contact_b)
        if not contact_b_obj:
            raise click.ClickException(f"Contact B not found: {contact_b}")

        contact_a_id = contact_a_obj["id"]
        contact_b_id = contact_b_obj["id"]
        label_a = contact_a_obj["canonical_label"]
        label_b = contact_b_obj["canonical_label"]

        if contact_a_id == contact_b_id:
            raise click.ClickException("Cannot merge a contact into itself")

        # Check if A is already archived
        if contact_a_obj["archived"]:
            raise click.ClickException(f"Contact A ({label_a}) is already archived")

        # Generate preview
        preview = get_merge_preview(conn, contact_a_id, contact_b_id)

        # Display preview
        click.echo("┌─────────────────────────────────────────────────┐")
        click.echo("│              MERGE PREVIEW                      │")
        click.echo("├─────────────────────────────────────────────────┤")
        click.echo(f"│ Source (A): {label_a[:35]:<36}│")
        click.echo(f"│   ID: {contact_a_id:<42}│")
        click.echo(f"│   Identifiers: {len(preview['identifiers_a']):<33}│")
        click.echo(f"│   Signals: {preview['signals_a']:<37}│")
        click.echo(f"│   Notes: {preview['notes_a']:<39}│")
        click.echo("├─────────────────────────────────────────────────┤")
        click.echo(f"│ Target (B): {label_b[:35]:<36}│")
        click.echo(f"│   ID: {contact_b_id:<42}│")
        click.echo(f"│   Identifiers: {len(preview['identifiers_b']):<33}│")
        click.echo(f"│   Signals: {preview['signals_b']:<37}│")
        click.echo(f"│   Notes: {preview['notes_b']:<39}│")
        click.echo("├─────────────────────────────────────────────────┤")
        click.echo("│ After merge, B will have:                       │")
        total_idents = len(preview['identifiers_a']) + len(preview['identifiers_b'])
        total_signals = preview['signals_a'] + preview['signals_b']
        total_notes = preview['notes_a'] + preview['notes_b'] + 2  # +2 for merge notes
        click.echo(f"│   Identifiers: {total_idents:<33}│")
        click.echo(f"│   Signals: {total_signals:<37}│")
        click.echo(f"│   Notes: {total_notes:<39}│")
        click.echo("│                                                 │")
        click.echo("│ Contact A will be ARCHIVED                      │")
        click.echo("└─────────────────────────────────────────────────┘")

        # Confirm
        if not confirm:
            if not click.confirm("Proceed with merge?"):
                click.echo("Merge cancelled.")
                return

        # Execute merge
        execute_merge(conn, contact_a_id, contact_b_id, label_a, label_b)

        click.echo(f"\n✓ Merged {label_a} → {label_b}")
        click.echo(f"  Contact {label_a} is now archived")

    except Exception as e:
        conn.rollback()
        if isinstance(e, click.ClickException):
            raise
        raise click.ClickException(str(e))
    finally:
        conn.close()
