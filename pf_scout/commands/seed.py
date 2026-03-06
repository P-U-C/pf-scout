"""pf-scout seed command."""

import csv
import json
import uuid
from datetime import datetime

import click

from ..db import get_connection
from ..fingerprint import compute_event_fingerprint
from ..collectors.github import GitHubCollector
from .seed_postfiat import seed_postfiat


@click.group("seed")
def seed_group():
    """Seed contacts from external sources."""
    pass


seed_group.add_command(seed_postfiat)


@seed_group.command("csv")
@click.option("--file", "csv_file", required=True, type=click.Path(exists=True),
              help="Path to CSV file with prospects")
@click.pass_context
def seed_csv(ctx, csv_file):
    """Seed contacts from a CSV file.

    CSV format:
        label,platform,identifier
        Alice Smith,github,alicesmith
        Bob Jones,twitter,bobjones
    """
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    created_count = 0
    skipped_count = 0

    try:
        with open(csv_file, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            # Validate required columns
            required_cols = {'label', 'platform', 'identifier'}
            if not required_cols.issubset(set(reader.fieldnames or [])):
                raise click.ClickException(
                    f"CSV must have columns: {', '.join(required_cols)}"
                )

            for row in reader:
                label = row['label'].strip()
                platform = row['platform'].strip().lower()
                identifier_value = row['identifier'].strip()

                if not all([label, platform, identifier_value]):
                    click.echo(f"  Skipping empty row: {row}")
                    skipped_count += 1
                    continue

                now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

                # Check if identifier already exists
                existing = conn.execute(
                    "SELECT id, contact_id FROM identifiers "
                    "WHERE platform = ? AND identifier_value = ?",
                    (platform, identifier_value)
                ).fetchone()

                if existing:
                    click.echo(f"  Skipped (exists): {platform}:{identifier_value}")
                    skipped_count += 1
                    continue

                # Create new contact + identifier
                contact_id = str(uuid.uuid4())
                ident_id = str(uuid.uuid4())

                conn.execute(
                    "INSERT INTO contacts "
                    "(id, canonical_label, first_seen, last_updated) "
                    "VALUES (?, ?, ?, ?)",
                    (contact_id, label, now, now)
                )
                conn.execute(
                    "INSERT INTO identifiers "
                    "(id, contact_id, platform, identifier_value, is_primary, "
                    "first_seen, last_seen, link_confidence, link_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ident_id, contact_id, platform, identifier_value, 1,
                     now, now, 1.0, "csv_import")
                )
                click.echo(f"  Created: {label} ({platform}:{identifier_value})")
                created_count += 1

        conn.commit()
        click.echo(f"\n✓ Seed complete: {created_count} created, {skipped_count} skipped")

    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()


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
