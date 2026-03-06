"""pf-scout prospect — generate a scored prospect pipeline document."""

import json
from datetime import datetime
from pathlib import Path

import click
import requests
import yaml

from ..db import get_connection
from ..scoring import (
    DEFAULT_DIMENSIONS,
    QUANT_KEYWORDS,
    TECH_KEYWORDS,
    infer_role,
    score_contact,
    score_engagement_consistency,
    score_forecasting,
    score_operational_reliability,
    score_technical_depth,
)


# Re-export for backward compatibility with existing imports (e.g., tests)
__all__ = [
    "DEFAULT_DIMENSIONS",
    "TECH_KEYWORDS",
    "QUANT_KEYWORDS",
    "score_technical_depth",
    "score_forecasting",
    "score_operational_reliability",
    "score_engagement_consistency",
    "score_row",
    "generate_document",
]


def score_row(row: dict, dimensions: list[dict]) -> dict:
    """Score a single leaderboard row against the given dimensions.

    This is a thin wrapper around scoring.score_contact for backward
    compatibility with existing code and tests.
    """
    return score_contact(row, dimensions)


def _fetch_leaderboard(jwt: str, base_url: str) -> list[dict]:
    """Fetch live leaderboard data from the Post Fiat API."""
    resp = requests.get(
        f"{base_url}/api/leaderboard",
        headers={
            "Authorization": f"Bearer {jwt}",
            "User-Agent": "pf-scout/0.1.0",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("rows", [])


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


def _load_rubric(rubric_path: str) -> tuple[str, list[dict]]:
    """Load and parse a rubric YAML file."""
    with open(rubric_path) as f:
        rubric = yaml.safe_load(f)
    name = rubric.get("name", Path(rubric_path).stem)
    dims = []
    for d in rubric.get("dimensions", []):
        dims.append({
            "key": d["key"],
            "label": d.get("label", d["key"]),
            "weight": d.get("weight", 1),
            "description": d.get("guide", ""),
        })
    return name, dims


def generate_document(
    rows: list[dict],
    dimensions: list[dict],
    rubric_name: str,
    title: str,
    min_composite: int,
) -> str:
    """Score all rows and generate the markdown pipeline document.

    Args:
        rows: List of leaderboard row dictionaries.
        dimensions: List of dimension dicts from rubric.
        rubric_name: Name of the rubric for display.
        title: Document title prefix.
        min_composite: Minimum composite score to include.

    Returns:
        Markdown document string.
    """
    today = datetime.utcnow().strftime("%Y-%m-%d")
    scored = []
    for row in rows:
        result = score_row(row, dimensions)
        if result["composite"] < min_composite:
            continue
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

    tier_counts = {}
    for s in scored:
        tier_counts[s["tier"]] = tier_counts.get(s["tier"], 0) + 1

    lines = []
    lines.append(f"# {title} — Prospect Pipeline\n")
    lines.append(
        f"*Generated {today} | {len(scored)} contributors scored | Rubric: {rubric_name}*\n"
    )
    lines.append("---\n")

    # Executive Summary
    lines.append("## Executive Summary\n")
    tier_summary = ", ".join(f"{v} {k}" for k, v in tier_counts.items())
    top3 = scored[:3]
    top3_text = "; ".join(
        f"**{s['label']}** ({s['composite']}/{s['max']}, {s['role']})"
        for s in top3
    )
    lines.append(
        f"Scored {len(scored)} contributors across {len(dimensions)} dimensions. "
        f"Distribution: {tier_summary}. "
        f"Top 3: {top3_text}.\n"
    )
    lines.append("---\n")

    # Rubric table
    lines.append("## Scoring Rubric\n")
    lines.append("| Dimension | Weight | Description | Signal Sources |")
    lines.append("|-----------|--------|-------------|----------------|")
    for d in dimensions:
        desc = d.get("description", "").split("\n")[0].strip() or d["label"]
        lines.append(f"| {d['label']} | {d.get('weight', 1)} | {desc} | Leaderboard data |")
    lines.append("")
    lines.append("---\n")

    # Scored Prospect Table
    lines.append("## Scored Prospect Table\n")
    dim_headers = " | ".join(d["label"] for d in dimensions)
    lines.append(f"| # | Contributor | Identifier | {dim_headers} | Composite | Role | Priority |")
    sep = " | ".join("---" for _ in dimensions)
    lines.append(f"|---|-------------|------------|{sep}|-----------|------|----------|")
    for i, s in enumerate(scored, 1):
        dim_vals = " | ".join(str(s["scores"].get(d["key"], "-")) for d in dimensions)
        ident = f"`{s['wallet'][:12]}…`" if len(s["wallet"]) > 12 else f"`{s['wallet']}`"
        lines.append(
            f"| {i} | {s['label']} | {ident} | {dim_vals} | "
            f"{s['composite']}/{s['max']} | {s['role']} | {s['tier']} |"
        )
    lines.append("")
    lines.append("---\n")

    # Prospect Profiles
    lines.append("## Prospect Profiles\n")
    for i, s in enumerate(scored, 1):
        ident = s["wallet"]
        lines.append(f"### {i}. {s['label']}")
        lines.append(f"**Identifier:** `{ident}`")
        dim_summary = " · ".join(
            f"{d['label']}: {s['scores'].get(d['key'], '-')}"
            for d in dimensions
        )
        lines.append(f"**Composite:** {s['composite']}/{s['max']} | {dim_summary}")
        lines.append(f"**Tier:** {s['tier']}\n")

        for d in dimensions:
            score_val = s["scores"].get(d["key"], "-")
            evidence = evidence_sentence(s["row"], d["key"])
            lines.append(f"**{d['label']} ({score_val}/5):** {evidence}\n")

        # Assessment
        lines.append(
            f"**Assessment:** {s['label']} scores {s['composite']}/{s['max']} "
            f"({s['pct']:.0%}), placing in {s['tier']}. "
            f"Primary fit: {s['role']}.\n"
        )

        if "Top Tier" in s["tier"]:
            lines.append(
                f"**Recruitment angle:** Strong candidate for {s['role']} role. "
                f"Demonstrated consistent engagement and relevant skills "
                f"based on leaderboard performance.\n"
            )

        lines.append(
            "**Gaps:** On-chain leaderboard data only; "
            "no external portfolio, interview, or direct communication signal yet.\n"
        )
        lines.append("---\n")

    return "\n".join(lines)


@click.command("prospect")
@click.option("--rubric", "rubric_path", type=click.Path(exists=True), default=None,
              help="Rubric YAML file (default: built-in 4-dimension)")
@click.option("--jwt", default=None, envvar="PF_JWT_TOKEN",
              help="JWT token for live leaderboard fetch")
@click.option("--output", "output_path", type=click.Path(), default=None,
              help="Output file (default: stdout)")
@click.option("--from-db", "from_db", is_flag=True, default=False,
              help="Read from local DB instead of live API")
@click.option("--min-composite", type=int, default=0,
              help="Minimum composite score to include")
@click.option("--title", default="Post Fiat",
              help="Document title prefix")
@click.option("--base-url", default="https://tasknode.postfiat.org",
              help="Tasknode API base URL")
@click.pass_context
def prospect_cmd(ctx, rubric_path, jwt, output_path, from_db, min_composite, title, base_url):
    """Generate a scored prospect pipeline document."""
    # Load dimensions
    if rubric_path:
        rubric_name, dimensions = _load_rubric(rubric_path)
    else:
        rubric_name = "pf-default (4-dimension)"
        dimensions = DEFAULT_DIMENSIONS

    # Load data
    if from_db:
        db_path = ctx.obj["db_path"]
        rows = _load_from_db(db_path)
        if not rows:
            raise click.ClickException(
                "No postfiat/leaderboard signals in DB. Run: pf-scout seed postfiat first."
            )
        click.echo(f"Loaded {len(rows)} contributors from DB")
    else:
        if not jwt:
            raise click.ClickException(
                "JWT required for live mode. Pass --jwt or set PF_JWT_TOKEN, "
                "or use --from-db for stored data."
            )
        rows = _fetch_leaderboard(jwt, base_url)
        click.echo(f"Fetched {len(rows)} contributors from leaderboard")

    doc = generate_document(rows, dimensions, rubric_name, title, min_composite)

    if output_path:
        Path(output_path).write_text(doc)
        click.echo(f"Wrote prospect pipeline to {output_path}")
    else:
        click.echo(doc)
