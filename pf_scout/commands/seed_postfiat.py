"""pf-scout seed postfiat — seed contacts from the Post Fiat leaderboard API."""

import json
import uuid
from datetime import datetime

import click
import requests

from ..db import get_connection
from ..fingerprint import compute_event_fingerprint


@click.command("postfiat")
@click.option("--jwt", default=None, envvar="PF_JWT_TOKEN",
              help="JWT token for PF leaderboard API (or set PF_JWT_TOKEN)")
@click.option("--min-alignment", type=float, default=None,
              help="Minimum alignment_score to include")
@click.option("--min-monthly-pft", type=float, default=None,
              help="Minimum monthly_rewards to include")
@click.option("--base-url", default="https://tasknode.postfiat.org",
              help="Tasknode API base URL")
@click.pass_context
def seed_postfiat(ctx, jwt, min_alignment, min_monthly_pft, base_url):
    """Seed contacts from the Post Fiat leaderboard API."""
    if not jwt:
        raise click.ClickException(
            "JWT token required. Pass --jwt or set PF_JWT_TOKEN env var."
        )

    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    contacts_created = 0
    signals_inserted = 0
    skipped = 0

    try:
        click.echo("Fetching Post Fiat leaderboard...")
        resp = requests.get(
            f"{base_url}/api/leaderboard",
            headers={
                "Authorization": f"Bearer {jwt}",
                "User-Agent": "pf-scout/0.1.0",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("rows", [])
        click.echo(f"Found {len(rows)} contributors on leaderboard")

        for row in rows:
            wallet = row.get("wallet_address", "")
            if not wallet:
                continue

            # Apply filters
            if min_alignment is not None:
                if (row.get("alignment_score") or 0) < min_alignment:
                    skipped += 1
                    continue
            if min_monthly_pft is not None:
                if (row.get("monthly_rewards") or 0) < min_monthly_pft:
                    skipped += 1
                    continue

            now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            label = row.get("summary") or wallet

            # Check if identifier already exists
            existing = conn.execute(
                "SELECT id, contact_id FROM identifiers "
                "WHERE platform = ? AND identifier_value = ?",
                ("postfiat", wallet),
            ).fetchone()

            if existing:
                contact_id = existing["contact_id"]
                ident_id = existing["id"]
            else:
                # Create new contact + identifier
                contact_id = str(uuid.uuid4())
                ident_id = str(uuid.uuid4())

                conn.execute(
                    "INSERT INTO contacts (id, canonical_label, first_seen, last_updated) "
                    "VALUES (?, ?, ?, ?)",
                    (contact_id, label, now, now),
                )
                conn.execute(
                    "INSERT INTO identifiers "
                    "(id, contact_id, platform, identifier_value, is_primary, "
                    "first_seen, last_seen, link_confidence, link_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ident_id, contact_id, "postfiat", wallet, 1, now, now, 1.0, "seed"),
                )
                contacts_created += 1

            # Insert leaderboard signal
            payload = {
                "wallet_address": wallet,
                "summary": row.get("summary"),
                "capabilities": row.get("capabilities", []),
                "expert_knowledge": row.get("expert_knowledge", []),
                "monthly_rewards": row.get("monthly_rewards"),
                "monthly_tasks": row.get("monthly_tasks"),
                "weekly_rewards": row.get("weekly_rewards"),
                "alignment_score": row.get("alignment_score"),
                "alignment_tier": row.get("alignment_tier"),
                "sybil_score": row.get("sybil_score"),
                "sybil_risk": row.get("sybil_risk"),
                "leaderboard_score_month": row.get("leaderboard_score_month"),
                "leaderboard_score_week": row.get("leaderboard_score_week"),
                "is_published": row.get("is_published"),
                "user_id": row.get("user_id"),
            }

            fingerprint = compute_event_fingerprint(
                contact_id, "postfiat", "postfiat/leaderboard",
                wallet, payload,
            )

            payload_json = json.dumps(payload, sort_keys=True, ensure_ascii=True)

            cursor = conn.execute(
                "INSERT OR IGNORE INTO signals "
                "(contact_id, identifier_id, collected_at, signal_ts, source, signal_type, "
                "source_event_id, event_fingerprint, payload, evidence_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    contact_id, ident_id, now, now, "postfiat", "postfiat/leaderboard",
                    wallet, fingerprint, payload_json,
                    f"PF leaderboard: {label}",
                ),
            )
            if cursor.rowcount > 0:
                signals_inserted += 1

            # Update timestamps
            conn.execute(
                "UPDATE identifiers SET last_seen = ? WHERE id = ?", (now, ident_id)
            )
            conn.execute(
                "UPDATE contacts SET last_updated = ? WHERE id = ?", (now, contact_id)
            )

        conn.commit()
        click.echo(
            f"Seeded {contacts_created} contacts, {signals_inserted} signals "
            f"from postfiat leaderboard"
            + (f" ({skipped} filtered out)" if skipped else "")
        )

    except requests.RequestException as e:
        conn.rollback()
        raise click.ClickException(f"Leaderboard API error: {e}")
    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()
