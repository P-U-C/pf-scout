"""pf-scout report — generate reports from scored prospect data.

This command generates reports from DB snapshots (not live leaderboard),
using the shared scoring module for consistent evaluation.
"""

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import click

from ..db import get_connection
from ..rubric import load_rubric, RubricValidationError
from ..scoring import (
    DEFAULT_DIMENSIONS,
    score_contact,
    infer_role,
)


def _load_from_db(db_path: str) -> list[dict]:
    """Load leaderboard data from local database snapshots."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT payload FROM signals WHERE signal_type = 'postfiat/leaderboard' "
        "ORDER BY collected_at DESC"
    ).fetchall()
    conn.close()
    # Deduplicate by wallet
    seen = set()
    result = []
    for r in rows:
        payload = json.loads(r["payload"])
        wallet = payload.get("wallet_address")
        if wallet and wallet not in seen:
            seen.add(wallet)
            result.append(payload)
    return result


def _score_all(rows: list[dict], dimensions: list[dict]) -> list[dict]:
    """Score all rows and add metadata."""
    scored = []
    for row in rows:
        result = score_contact(row, dimensions)
        label = row.get("summary") or row.get("wallet_address", "unknown")
        wallet = row.get("wallet_address", "")
        role = infer_role(row)
        scored.append({
            "label": label,
            "wallet": wallet,
            "role": role,
            "row": row,
            **result,
        })
    scored.sort(key=lambda x: x["composite"], reverse=True)
    return scored


def _filter_by_tier(scored: list[dict], tier_filter: str) -> list[dict]:
    """Filter scored list by tier.

    Args:
        scored: List of scored contact dicts.
        tier_filter: 'top', 'mid', 'speculative', or 'all'.

    Returns:
        Filtered list.
    """
    tier_filter = tier_filter.lower()
    if tier_filter == "all":
        return scored

    tier_map = {
        "top": "🔴 Top Tier",
        "mid": "🟡 Mid Tier",
        "speculative": "⚪ Speculative",
    }
    target_tier = tier_map.get(tier_filter)
    if not target_tier:
        return scored

    return [s for s in scored if s["tier"] == target_tier]


def _generate_markdown(
    scored: list[dict],
    dimensions: list[dict],
    rubric_name: str,
    title: str,
) -> str:
    """Generate a markdown report."""
    today = datetime.utcnow().strftime("%Y-%m-%d")

    # Count tiers
    tier_counts = {}
    for s in scored:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1

    lines = []
    lines.append(f"# {title}\n")
    lines.append(f"*Generated {today} | {len(scored)} contacts | Rubric: {rubric_name}*\n")
    lines.append("---\n")

    # Summary statistics
    lines.append("## Summary\n")
    for tier, count in tier_counts.items():
        lines.append(f"- {tier}: {count}")
    lines.append("")

    if scored:
        avg_composite = sum(s["composite"] for s in scored) / len(scored)
        lines.append(f"- Average composite score: {avg_composite:.1f}/{scored[0]['max']}")
    lines.append("\n---\n")

    # Table
    lines.append("## Scored Contacts\n")
    dim_headers = " | ".join(d["label"] for d in dimensions)
    lines.append(f"| # | Name | Wallet | {dim_headers} | Composite | Role | Tier |")
    sep = " | ".join("---" for _ in dimensions)
    lines.append(f"|---|------|--------|{sep}|-----------|------|------|")

    for i, s in enumerate(scored, 1):
        dim_vals = " | ".join(str(s["scores"].get(d["key"], "-")) for d in dimensions)
        wallet_short = f"`{s['wallet'][:12]}…`" if len(s["wallet"]) > 12 else f"`{s['wallet']}`"
        lines.append(
            f"| {i} | {s['label']} | {wallet_short} | {dim_vals} | "
            f"{s['composite']}/{s['max']} | {s['role']} | {s['tier']} |"
        )

    lines.append("")
    return "\n".join(lines)


def _generate_csv(scored: list[dict], dimensions: list[dict]) -> str:
    """Generate a CSV report."""
    output = io.StringIO()

    # Build header
    fieldnames = ["rank", "name", "wallet", "role", "tier", "composite", "max", "pct"]
    fieldnames.extend(d["key"] for d in dimensions)

    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()

    for i, s in enumerate(scored, 1):
        row = {
            "rank": i,
            "name": s["label"],
            "wallet": s["wallet"],
            "role": s["role"],
            "tier": s["tier"],
            "composite": s["composite"],
            "max": s["max"],
            "pct": f"{s['pct']:.2%}",
        }
        for d in dimensions:
            row[d["key"]] = s["scores"].get(d["key"], "")
        writer.writerow(row)

    return output.getvalue()


def _generate_json(scored: list[dict], dimensions: list[dict], rubric_name: str) -> str:
    """Generate a JSON report."""
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "rubric": rubric_name,
        "dimensions": [d["key"] for d in dimensions],
        "total_contacts": len(scored),
        "contacts": [],
    }

    for i, s in enumerate(scored, 1):
        report["contacts"].append({
            "rank": i,
            "name": s["label"],
            "wallet": s["wallet"],
            "role": s["role"],
            "tier": s["tier"],
            "composite": s["composite"],
            "max": s["max"],
            "pct": round(s["pct"], 4),
            "scores": s["scores"],
        })

    return json.dumps(report, indent=2)


@click.command("report")
@click.option("--rubric", "rubric_path", type=click.Path(exists=True), default=None,
              help="Rubric YAML file (default: built-in 4-dimension)")
@click.option("--output", "-o", "output_path", type=click.Path(), default=None,
              help="Output file (default: stdout)")
@click.option("--format", "-f", "output_format", type=click.Choice(["markdown", "csv", "json"]),
              default="markdown", help="Output format")
@click.option("--tier", "tier_filter", type=click.Choice(["all", "top", "mid", "speculative"]),
              default="all", help="Filter by tier")
@click.option("--title", default="pf-scout Report",
              help="Report title (for markdown)")
@click.option("--min-composite", type=int, default=0,
              help="Minimum composite score to include")
@click.option("--limit", type=int, default=None,
              help="Maximum number of contacts to include")
@click.pass_context
def report_cmd(ctx, rubric_path, output_path, output_format, tier_filter, title, min_composite, limit):
    """Generate reports from DB snapshots.

    Uses stored leaderboard data (not live API) for consistent reporting.

    Examples:

        pf-scout report --format csv --tier top -o top-prospects.csv

        pf-scout report --rubric rubrics/custom.yaml --format json

        pf-scout report --min-composite 12 --limit 20
    """
    db_path = ctx.obj["db_path"]

    # Load dimensions
    if rubric_path:
        try:
            rubric = load_rubric(rubric_path)
            rubric_name = rubric["name"]
            dimensions = rubric["dimensions"]
        except RubricValidationError as e:
            raise click.ClickException(f"Invalid rubric: {'; '.join(e.errors)}")
    else:
        rubric_name = "pf-default (4-dimension)"
        dimensions = DEFAULT_DIMENSIONS

    # Load data from DB
    rows = _load_from_db(db_path)
    if not rows:
        raise click.ClickException(
            "No postfiat/leaderboard signals in DB. Run: pf-scout seed postfiat first."
        )

    click.echo(f"Loaded {len(rows)} contacts from DB", err=True)

    # Score all contacts
    scored = _score_all(rows, dimensions)

    # Apply filters
    if min_composite > 0:
        scored = [s for s in scored if s["composite"] >= min_composite]

    scored = _filter_by_tier(scored, tier_filter)

    if limit:
        scored = scored[:limit]

    click.echo(f"Reporting on {len(scored)} contacts (tier={tier_filter}, min={min_composite})", err=True)

    # Generate output
    if output_format == "markdown":
        output = _generate_markdown(scored, dimensions, rubric_name, title)
    elif output_format == "csv":
        output = _generate_csv(scored, dimensions)
    elif output_format == "json":
        output = _generate_json(scored, dimensions, rubric_name)
    else:
        raise click.ClickException(f"Unknown format: {output_format}")

    # Write output
    if output_path:
        Path(output_path).write_text(output)
        click.echo(f"Wrote report to {output_path}", err=True)
    else:
        click.echo(output)
