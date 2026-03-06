"""pf-scout diff command — compare snapshots to show score drift."""

import json
from datetime import datetime

import click

from ..db import get_connection


def format_delta(before, after):
    """Format delta between two numeric values."""
    if before is None:
        return f"+{after}" if after > 0 else str(after)
    delta = after - before
    if delta > 0:
        return f"+{delta}"
    elif delta < 0:
        return str(delta)
    else:
        return "0"


def format_tier_delta(before_tier, after_tier):
    """Format tier change indicator."""
    tier_order = {"D": 0, "C": 1, "Mid": 2, "B": 3, "Top": 4, "A": 5}
    before_rank = tier_order.get(before_tier, 0)
    after_rank = tier_order.get(after_tier, 0)
    if after_rank > before_rank:
        return "↑"
    elif after_rank < before_rank:
        return "↓"
    else:
        return "="


def render_diff_table(contact_label, identifier, snap_after, snap_before):
    """Render a diff table comparing two snapshots."""
    after_ts = snap_after["snapshot_ts"][:10]
    after_id = snap_after["id"]
    before_ts = snap_before["snapshot_ts"][:10]
    before_id = snap_before["id"]

    after_scores = json.loads(snap_after["dimension_scores"])
    before_scores = json.loads(snap_before["dimension_scores"])

    lines = []
    lines.append(f"Contact: {contact_label} ({identifier})")
    lines.append(f"Snapshot: #{after_id} ({after_ts}) vs #{before_id} ({before_ts})")
    lines.append("")

    # Build table
    header = "| Dimension       | Before | After | Δ   |"
    sep = "|-----------------|--------|-------|-----|"
    lines.append(header)
    lines.append(sep)

    # Get all dimension keys from both snapshots
    all_keys = set(before_scores.keys()) | set(after_scores.keys())

    for key in sorted(all_keys):
        before_data = before_scores.get(key, {})
        after_data = after_scores.get(key, {})

        before_val = before_data.get("score", 0) if isinstance(before_data, dict) else before_data
        after_val = after_data.get("score", 0) if isinstance(after_data, dict) else after_data

        delta = format_delta(before_val, after_val)
        dim_label = key.replace("_", " ").title()[:15]
        lines.append(f"| {dim_label:<15} | {before_val:<6} | {after_val:<5} | {delta:<3} |")

    # Add totals
    before_total = snap_before["total_score"]
    after_total = snap_after["total_score"]
    total_delta = format_delta(before_total, after_total)
    lines.append(f"| {'Total':<15} | {before_total:<6.0f} | {after_total:<5.0f} | {total_delta:<3} |")

    # Add tier
    before_tier = snap_before["tier"]
    after_tier = snap_after["tier"]
    tier_delta = format_tier_delta(before_tier, after_tier)
    lines.append(f"| {'Tier':<15} | {before_tier:<6} | {after_tier:<5} | {tier_delta:<3} |")

    return "\n".join(lines)


@click.command("diff")
@click.argument("identifier")
@click.option("--since", default=None, help="Compare against snapshot from this date (YYYY-MM-DD)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]),
              default="text", help="Output format")
@click.pass_context
def diff_command(ctx, identifier, since, output_format):
    """Compare snapshots to show score drift over time.

    IDENTIFIER should be in platform:value format (e.g., github:alice).

    By default, compares the latest snapshot to the previous one.
    Use --since to compare against a snapshot from a specific date.
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

        # Get contact label
        contact = conn.execute(
            "SELECT canonical_label FROM contacts WHERE id = ?", (contact_id,)
        ).fetchone()
        contact_label = contact["canonical_label"]

        # Query snapshots for this contact, ordered by snapshot_ts DESC
        snapshots = conn.execute(
            """SELECT * FROM snapshots 
               WHERE contact_id = ? 
               ORDER BY snapshot_ts DESC""",
            (contact_id,)
        ).fetchall()

        if len(snapshots) < 1:
            raise click.ClickException(f"No snapshots found for {identifier}")

        # Get the latest snapshot
        snap_after = snapshots[0]
        snap_before = None

        if since:
            # Find snapshot from or before the specified date
            since_date = since + "T23:59:59Z"  # End of day
            for snap in snapshots[1:]:  # Skip the latest
                if snap["snapshot_ts"] <= since_date:
                    snap_before = snap
                    break

            if not snap_before:
                # Try to find any snapshot before the since date
                for snap in snapshots:
                    if snap["snapshot_ts"] <= since_date and snap["id"] != snap_after["id"]:
                        snap_before = snap
                        break

            if not snap_before:
                raise click.ClickException(
                    f"No snapshot found on or before {since} for {identifier}"
                )
        else:
            # Get the previous snapshot
            if len(snapshots) < 2:
                raise click.ClickException(
                    f"Only one snapshot exists for {identifier}. Need at least 2 to diff."
                )
            snap_before = snapshots[1]

        if output_format == "json":
            result = {
                "contact": contact_label,
                "identifier": identifier,
                "after": {
                    "id": snap_after["id"],
                    "snapshot_ts": snap_after["snapshot_ts"],
                    "dimension_scores": json.loads(snap_after["dimension_scores"]),
                    "total_score": snap_after["total_score"],
                    "weighted_score": snap_after["weighted_score"],
                    "tier": snap_after["tier"],
                },
                "before": {
                    "id": snap_before["id"],
                    "snapshot_ts": snap_before["snapshot_ts"],
                    "dimension_scores": json.loads(snap_before["dimension_scores"]),
                    "total_score": snap_before["total_score"],
                    "weighted_score": snap_before["weighted_score"],
                    "tier": snap_before["tier"],
                },
            }
            click.echo(json.dumps(result, indent=2))
        else:
            click.echo(render_diff_table(contact_label, identifier, snap_after, snap_before))

    finally:
        conn.close()
