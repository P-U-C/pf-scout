"""pf-scout list command — show all contacts with latest scores."""

import csv
import io
import json

import click
import yaml

from ..db import get_connection


def load_rubric(rubric_path):
    """Load a YAML rubric file."""
    with open(rubric_path) as f:
        return yaml.safe_load(f)


@click.command("list")
@click.option("--tier", type=click.Choice(["top", "mid", "speculative", "low"]),
              help="Filter by tier")
@click.option("--rubric", "rubric_path", type=click.Path(exists=True),
              help="Use specific rubric for filtering")
@click.option("--format", "output_format", type=click.Choice(["text", "json", "csv"]),
              default="text", help="Output format")
@click.option("--limit", type=int, default=None, help="Maximum number of contacts to show")
@click.pass_context
def list_command(ctx, tier, rubric_path, output_format, limit):
    """List all contacts with their latest scores.

    Shows contacts ordered by weighted score (descending).
    Use --tier to filter by score tier, --format for different outputs.
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    rubric_name = None
    if rubric_path:
        rubric = load_rubric(rubric_path)
        rubric_name = rubric.get("name")

    try:
        # Build query for contacts with latest snapshot
        query = """
            SELECT c.id, c.canonical_label, c.first_seen, c.last_updated,
                   c.tags, c.notes_count, c.archived,
                   s.weighted_score, s.total_score, s.tier, s.snapshot_ts, s.rubric_name
            FROM contacts c
            LEFT JOIN snapshots s ON s.id = (
                SELECT id FROM snapshots
                WHERE contact_id = c.id
        """
        params = []

        if rubric_name:
            query += " AND rubric_name = ?"
            params.append(rubric_name)

        query += """
                ORDER BY snapshot_ts DESC LIMIT 1
            )
            WHERE c.archived = 0
        """

        # Filter by tier if specified
        if tier:
            query += " AND LOWER(s.tier) = ?"
            params.append(tier.lower())

        query += " ORDER BY s.weighted_score DESC NULLS LAST, c.canonical_label ASC"

        if limit:
            query += " LIMIT ?"
            params.append(limit)

        rows = conn.execute(query, params).fetchall()

        # Get identifiers for each contact
        results = []
        for row in rows:
            contact_id = row["id"]

            # Get primary identifier
            ident_row = conn.execute(
                "SELECT platform, identifier_value FROM identifiers "
                "WHERE contact_id = ? ORDER BY is_primary DESC LIMIT 1",
                (contact_id,)
            ).fetchone()

            primary_ident = f"{ident_row['platform']}:{ident_row['identifier_value']}" if ident_row else "—"

            results.append({
                "id": contact_id,
                "label": row["canonical_label"],
                "primary_identifier": primary_ident,
                "score": row["weighted_score"] or 0,
                "total_score": row["total_score"] or 0,
                "tier": row["tier"] or "—",
                "rubric": row["rubric_name"] or "—",
                "snapshot_ts": (row["snapshot_ts"] or "")[:10],
                "last_updated": (row["last_updated"] or "")[:10],
                "notes_count": row["notes_count"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
            })

        # Output results
        if output_format == "json":
            click.echo(json.dumps(results, indent=2))

        elif output_format == "csv":
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=[
                "label", "primary_identifier", "tier", "score", "total_score",
                "rubric", "snapshot_ts", "last_updated", "notes_count"
            ])
            writer.writeheader()
            for r in results:
                writer.writerow({
                    "label": r["label"],
                    "primary_identifier": r["primary_identifier"],
                    "tier": r["tier"],
                    "score": r["score"],
                    "total_score": r["total_score"],
                    "rubric": r["rubric"],
                    "snapshot_ts": r["snapshot_ts"],
                    "last_updated": r["last_updated"],
                    "notes_count": r["notes_count"],
                })
            click.echo(output.getvalue().strip())

        else:
            # Text format
            if not results:
                click.echo("No contacts found.")
                return

            # Header
            tier_filter = f" (tier: {tier})" if tier else ""
            rubric_filter = f" (rubric: {rubric_name})" if rubric_name else ""
            limit_info = f" (showing {len(results)})" if limit else f" ({len(results)} total)"
            click.echo(f"\nContacts{tier_filter}{rubric_filter}{limit_info}\n")

            click.echo(f"{'#':<4} {'Contact':<22} {'Identifier':<25} {'Tier':<12} {'Score':<7} {'Updated'}")
            click.echo("─" * 85)

            for i, r in enumerate(results, 1):
                ident_display = r["primary_identifier"][:24] if len(r["primary_identifier"]) > 24 else r["primary_identifier"]
                label_display = r["label"][:21] if len(r["label"]) > 21 else r["label"]
                click.echo(
                    f"{i:<4} {label_display:<22} {ident_display:<25} "
                    f"{r['tier']:<12} {r['score']:<7.1f} {r['last_updated']}"
                )

            click.echo()

    finally:
        conn.close()
