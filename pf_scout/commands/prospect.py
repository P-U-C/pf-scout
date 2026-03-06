"""pf-scout prospect — generate a scored prospect pipeline document."""

import json
from datetime import datetime
from pathlib import Path

import click
import requests
import yaml

from ..db import get_connection


# ---------------------------------------------------------------------------
# Default scoring dimensions (used when no rubric YAML provided)
# ---------------------------------------------------------------------------

TECH_KEYWORDS = [
    "infrastructure", "devops", "backend", "engineering", "smart contract",
    "blockchain", "solidity", "rust", "python", "go", "typescript",
    "kubernetes", "docker", "cloud", "aws", "api", "protocol", "security",
    "cryptography", "zk", "evm", "validator", "rpc",
]

QUANT_KEYWORDS = [
    "quant", "quantitative", "machine learning", "ml", "statistics",
    "trading", "signal", "forecasting", "data science", "analytics",
    "on-chain", "onchain", "backtesting", "risk management", "portfolio",
    "financial modeling", "time series", "alpha", "macro", "research",
    "modeling", "prediction", "probability",
]

DEFAULT_DIMENSIONS = [
    {"key": "technical_depth", "label": "Technical Depth", "weight": 1},
    {"key": "forecasting", "label": "Forecasting / Quantitative Potential", "weight": 1},
    {"key": "operational_reliability", "label": "Operational Reliability", "weight": 1},
    {"key": "engagement_consistency", "label": "Engagement Consistency", "weight": 1},
]


def _text_blob(row: dict) -> str:
    """Concatenate all text fields from a leaderboard row for keyword search."""
    parts = []
    if row.get("summary"):
        parts.append(str(row["summary"]))
    for cap in row.get("capabilities") or []:
        if isinstance(cap, dict):
            parts.append(" ".join(str(v) for v in cap.values()))
        else:
            parts.append(str(cap))
    for ek in row.get("expert_knowledge") or []:
        if isinstance(ek, dict):
            parts.append(" ".join(str(v) for v in ek.values()))
        else:
            parts.append(str(ek))
    return " ".join(parts).lower()


def _count_keyword_hits(text: str, keywords: list[str]) -> int:
    """Count how many distinct keywords appear in text."""
    return sum(1 for kw in keywords if kw in text)


def _hits_to_base(hits: int) -> int:
    if hits == 0:
        return 1
    if hits == 1:
        return 2
    if hits == 2:
        return 3
    if hits <= 4:
        return 4
    return 5


def score_technical_depth(row: dict) -> int:
    text = _text_blob(row)
    base = _hits_to_base(_count_keyword_hits(text, TECH_KEYWORDS))
    if (row.get("sybil_score") or 0) >= 85:
        base += 1
    return min(base, 5)


def score_forecasting(row: dict) -> int:
    text = _text_blob(row)
    base = _hits_to_base(_count_keyword_hits(text, QUANT_KEYWORDS))
    if (row.get("alignment_score") or 0) >= 90:
        base += 1
    if (row.get("monthly_rewards") or 0) > 500000:
        base += 1
    return min(base, 5)


def score_operational_reliability(row: dict) -> int:
    lsm = row.get("leaderboard_score_month") or 0
    if lsm < 15:
        base = 1
    elif lsm < 40:
        base = 2
    elif lsm < 60:
        base = 3
    elif lsm < 80:
        base = 4
    else:
        base = 5
    if (row.get("monthly_tasks") or 0) >= 30:
        base += 1
    monthly = row.get("monthly_rewards") or 0
    weekly = row.get("weekly_rewards") or 0
    if monthly > 0:
        ratio = weekly / monthly
        if 0.2 <= ratio <= 0.35:
            base += 1
    return min(base, 5)


def score_engagement_consistency(row: dict) -> int:
    weekly = row.get("weekly_rewards") or 0
    if weekly <= 0:
        base = 1
    elif weekly <= 50000:
        base = 2
    elif weekly <= 150000:
        base = 3
    elif weekly <= 300000:
        base = 4
    else:
        base = 5
    if (row.get("leaderboard_score_week") or 0) > 50:
        base += 1
    return min(base, 5)


SCORERS = {
    "technical_depth": score_technical_depth,
    "forecasting": score_forecasting,
    "operational_reliability": score_operational_reliability,
    "engagement_consistency": score_engagement_consistency,
}


def score_row(row: dict, dimensions: list[dict]) -> dict:
    """Score a single leaderboard row against the given dimensions."""
    scores = {}
    for dim in dimensions:
        key = dim["key"]
        scorer = SCORERS.get(key)
        scores[key] = scorer(row) if scorer else 1
    composite = sum(scores.values())
    max_possible = len(dimensions) * 5
    pct = composite / max_possible if max_possible else 0
    if pct >= 0.8:
        tier = "🔴 Top Tier"
    elif pct >= 0.6:
        tier = "🟡 Mid Tier"
    else:
        tier = "⚪ Speculative"
    return {
        "scores": scores,
        "composite": composite,
        "max": max_possible,
        "pct": pct,
        "tier": tier,
    }


def _evidence_sentence(row: dict, dim_key: str) -> str:
    """Generate a brief evidence sentence for a dimension score."""
    text = _text_blob(row)
    if dim_key == "technical_depth":
        hits = [kw for kw in TECH_KEYWORDS if kw in text]
        if hits:
            return f"Keywords matched: {', '.join(hits[:5])}."
        return "No technical keywords found in profile."
    if dim_key == "forecasting":
        hits = [kw for kw in QUANT_KEYWORDS if kw in text]
        if hits:
            return f"Keywords matched: {', '.join(hits[:5])}."
        return "No quantitative keywords found in profile."
    if dim_key == "operational_reliability":
        lsm = row.get("leaderboard_score_month") or 0
        mt = row.get("monthly_tasks") or 0
        return f"Leaderboard score (month): {lsm}, monthly tasks: {mt}."
    if dim_key == "engagement_consistency":
        wr = row.get("weekly_rewards") or 0
        lsw = row.get("leaderboard_score_week") or 0
        return f"Weekly rewards: {wr:,.0f}, leaderboard score (week): {lsw}."
    return "No evidence available."


def _infer_role(row: dict) -> str:
    text = _text_blob(row)
    if any(kw in text for kw in ["trading", "quant", "alpha", "signal"]):
        return "Signal / Quant"
    if any(kw in text for kw in ["infrastructure", "devops", "kubernetes", "docker"]):
        return "Infrastructure"
    if any(kw in text for kw in ["smart contract", "solidity", "evm", "blockchain"]):
        return "Protocol Engineer"
    if any(kw in text for kw in ["research", "analytics", "data science"]):
        return "Researcher"
    return "Contributor"


def _fetch_leaderboard(jwt: str, base_url: str) -> list[dict]:
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
    """Score all rows and generate the markdown pipeline document."""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    scored = []
    for row in rows:
        result = score_row(row, dimensions)
        if result["composite"] < min_composite:
            continue
        label = row.get("summary") or row.get("wallet_address", "unknown")
        wallet = row.get("wallet_address", "")
        role = _infer_role(row)
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
            evidence = _evidence_sentence(s["row"], d["key"])
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
