"""pf-scout seed command."""

import json
import uuid
from datetime import datetime

import click

from ..db import get_connection
from ..fingerprint import compute_event_fingerprint
from ..collectors.github import GitHubCollector


@click.group("seed")
def seed_group():
    """Seed contacts from external sources."""
    pass


@seed_group.command("github")
@click.option("--org", required=True, help="GitHub organization name")
@click.option("--token", default=None, envvar="GITHUB_TOKEN",
              help="GitHub API token")
@click.pass_context
def seed_github(ctx, org, token):
    """Seed contacts from a GitHub organization's contributors."""
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)
    collector = GitHubCollector()

    contacts_created = 0
    signals_inserted = 0

    try:
        # Discover contributors
        click.echo(f"Discovering contributors from github:{org}...")
        identifiers = collector.discover(org, token)
        click.echo(f"Found {len(identifiers)} contributors")

        for platform, ident_value in identifiers:
            now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

            # Check if identifier already exists
            existing = conn.execute(
                "SELECT id, contact_id FROM identifiers WHERE platform = ? AND identifier_value = ?",
                (platform, ident_value)
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
                    (contact_id, ident_value, now, now)
                )
                conn.execute(
                    "INSERT INTO identifiers "
                    "(id, contact_id, platform, identifier_value, is_primary, "
                    "first_seen, last_seen, link_confidence, link_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ident_id, contact_id, platform, ident_value, 1, now, now, 1.0, "seed")
                )
                contacts_created += 1

            # Collect signals
            collected = collector.collect(ident_value, contact_id, token)

            for sig in collected:
                fingerprint = compute_event_fingerprint(
                    contact_id, sig.source, sig.signal_type,
                    sig.source_event_id, sig.payload
                )

                payload_json = json.dumps(sig.payload, sort_keys=True, ensure_ascii=True)

                cursor = conn.execute(
                    "INSERT OR IGNORE INTO signals "
                    "(contact_id, identifier_id, collected_at, signal_ts, source, signal_type, "
                    "source_event_id, event_fingerprint, payload, evidence_note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (contact_id, ident_id, now, sig.signal_ts, sig.source, sig.signal_type,
                     sig.source_event_id, fingerprint, payload_json, sig.evidence_note)
                )
                if cursor.rowcount > 0:
                    signals_inserted += 1

            # Update last_seen on identifier
            conn.execute(
                "UPDATE identifiers SET last_seen = ? WHERE id = ?",
                (now, ident_id)
            )
            # Update last_updated on contact
            conn.execute(
                "UPDATE contacts SET last_updated = ? WHERE id = ?",
                (now, contact_id)
            )

        conn.commit()
        click.echo(f"Seeded {contacts_created} contacts, {signals_inserted} signals from github:{org}")

    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()
