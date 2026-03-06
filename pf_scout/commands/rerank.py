"""pf-scout rerank — re-rank contacts against current context alignment."""
import json
import re
from pathlib import Path
import click
import yaml

from ..db import get_connection


def _load_context_keywords(context_md: str) -> list[str]:
    """Extract meaningful keywords from a Context document for alignment matching."""
    # Strip markdown syntax, extract words
    text = re.sub(r"[#*`\[\]()>]", " ", context_md).lower()
    # Focus on common PF/crypto/tech signals
    words = re.findall(r"\b[a-z]{4,}\b", text)
    # Remove stopwords
    stopwords = {"this", "that", "with", "from", "have", "will", "your", "their",
                 "been", "they", "what", "when", "which", "more", "also", "into",
                 "then", "than", "other", "some", "each", "about"}
    return [w for w in words if w not in stopwords]


def _alignment_notes(my_keywords: list[str], prospect_context: str) -> list[str]:
    """Keyword-based alignment — word-boundary matching to avoid false positives."""
    if not prospect_context:
        return []
    prospect_lower = prospect_context.lower()
    matches = [kw for kw in set(my_keywords)
               if re.search(r'\b' + re.escape(kw) + r'\b', prospect_lower)]
    return sorted(matches)[:8]


@click.command("rerank")
@click.option("--rubric", "rubric_path", type=click.Path(exists=True), help="Rubric YAML")
@click.option("--format", "fmt", type=click.Choice(["md", "json", "csv"]), default="md")
@click.option("--tier", type=click.Choice(["top", "mid", "speculative"]), help="Filter by tier")
@click.pass_context
def rerank_cmd(ctx, rubric_path, fmt, tier):
    """Re-rank all contacts by fit against your current PF Context. Read-only."""
    db_path = ctx.obj["db_path"]
    scout_dir = Path(db_path).parent
    context_path = scout_dir / "my-context.md"
    state_path = scout_dir / "context-state.json"

    # Load recruiter context
    if not context_path.exists():
        click.echo("⚠  No context set. Run: pf-scout set-context --cookie \"$PF_SESSION\"")
        my_context_md = ""
        my_keywords = []
        context_version = "none"
    else:
        my_context_md = context_path.read_text()
        my_keywords = _load_context_keywords(my_context_md)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        context_version = state.get("version_label", "unknown")

    conn = get_connection(db_path)

    # Load rubric if provided
    rubric_name = "none"
    if rubric_path:
        with open(rubric_path) as f:
            rubric = yaml.safe_load(f)
        rubric_name = rubric.get("name", rubric_path)

    # Get all active contacts with latest snapshot + latest postfiat/context signal
    rows = conn.execute("""
        SELECT c.id, c.canonical_label,
               s.weighted_score, s.tier, s.snapshot_ts, s.rubric_name
        FROM contacts c
        LEFT JOIN snapshots s ON s.id = (
            SELECT id FROM snapshots
            WHERE contact_id = c.id
            ORDER BY snapshot_ts DESC LIMIT 1
        )
        WHERE c.archived = 0
        ORDER BY s.weighted_score DESC NULLS LAST
    """).fetchall()

    results = []
    for row in rows:
        contact_id = row["id"]
        label = row["canonical_label"]
        score = row["weighted_score"] or 0
        tier_label = row["tier"] or "—"
        snap_ts = (row["snapshot_ts"] or "")[:10]
        rubric_label = row["rubric_name"] or "—"

        # Filter by tier if requested
        if tier and tier not in (tier_label or "").lower():
            continue

        # Get latest postfiat/context signal
        ctx_row = conn.execute("""
            SELECT payload FROM signals
            WHERE contact_id = ? AND signal_type = 'postfiat/context'
            ORDER BY collected_at DESC LIMIT 1
        """, (contact_id,)).fetchone()

        alignment = []
        context_status = "⚠ no PF context"
        if ctx_row:
            payload = json.loads(ctx_row["payload"])
            if payload.get("auth_required"):
                context_status = "🔒 auth required"
            else:
                raw = payload.get("raw_markdown", "")
                alignment = _alignment_notes(my_keywords, raw)
                context_status = f"✅ {len(alignment)} keyword matches" if alignment else "📄 fetched, no match"

        results.append({
            "label": label,
            "score": score,
            "tier": tier_label,
            "snap_ts": snap_ts,
            "rubric": rubric_label,
            "context_status": context_status,
            "alignment": alignment,
        })

    # Output
    if fmt == "md":
        click.echo(f"\nRERANK — {rubric_name} | Your context: {context_version} | {len(results)} contacts\n")
        click.echo(f"{'Rank':<5} {'Contact':<22} {'Tier':<14} {'Score':<7} {'Context Alignment'}")
        click.echo("─" * 80)
        for i, r in enumerate(results, 1):
            alignment_str = ", ".join(r["alignment"][:4]) if r["alignment"] else r["context_status"]
            click.echo(f"{i:<5} {r['label']:<22} {r['tier']:<14} {r['score']:<7.1f} {alignment_str}")
    elif fmt == "json":
        click.echo(json.dumps(results, indent=2))
    elif fmt == "csv":
        click.echo("rank,label,tier,score,context_status,alignment_keywords")
        for i, r in enumerate(results, 1):
            click.echo(f"{i},{r['label']},{r['tier']},{r['score']},{r['context_status']},{';'.join(r['alignment'])}")

    conn.close()
