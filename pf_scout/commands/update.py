"""pf-scout update command."""

import json
import sys
from datetime import datetime, timedelta

import click
import yaml

from ..db import get_connection
from ..fingerprint import compute_event_fingerprint
from ..collectors.github import GitHubCollector


def get_collector_for_platform(platform):
    """Return the appropriate collector for a platform."""
    if platform == "github":
        return GitHubCollector()
    return None


def load_rubric(rubric_path):
    """Load a YAML rubric file."""
    with open(rubric_path) as f:
        return yaml.safe_load(f)


def determine_tier(weighted_score, tiers):
    """Determine tier based on weighted score."""
    for tier in tiers:
        if weighted_score >= tier["min_score"]:
            return tier["name"]
    return tiers[-1]["name"] if tiers else "D"


def collect_signals_for_contact(conn, contact_id, token=None):
    """Re-collect signals for all identifiers of a contact.

    Returns (new_count, existing_count, errors).
    """
    identifiers = conn.execute(
        "SELECT * FROM identifiers WHERE contact_id = ?", (contact_id,)
    ).fetchall()

    new_count = 0
    existing_count = 0
    errors = []

    for ident in identifiers:
        platform = ident["platform"]
        ident_value = ident["identifier_value"]
        ident_id = ident["id"]

        collector = get_collector_for_platform(platform)
        if not collector:
            continue

        try:
            signals = collector.collect(ident_value, contact_id, token)
        except Exception as e:
            errors.append(f"{platform}:{ident_value}: {e}")
            continue

        now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

        for sig in signals:
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
                new_count += 1
            else:
                existing_count += 1

        # Update last_seen
        conn.execute(
            "UPDATE identifiers SET last_seen = ? WHERE id = ?",
            (now, ident_id)
        )

    # Update contact last_updated
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    conn.execute(
        "UPDATE contacts SET last_updated = ? WHERE id = ?",
        (now, contact_id)
    )

    return new_count, existing_count, errors


def run_scoring(conn, contact_id, rubric, batch=False):
    """Run manual scoring flow for a contact.

    In interactive mode: prompts user for each dimension score.
    In batch mode: creates snapshot with all dims scored 0, needs_review=True.
    """
    now = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    # Get contact info
    contact = conn.execute(
        "SELECT * FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()

    # Get signals for context
    signals = conn.execute(
        "SELECT * FROM signals WHERE contact_id = ? ORDER BY collected_at DESC",
        (contact_id,)
    ).fetchall()

    dimensions = rubric.get("dimensions", [])
    tiers = rubric.get("tiers", [])
    rubric_name = rubric.get("name", "unknown")
    rubric_version = rubric.get("version", "1.0")

    dimension_scores = {}
    signal_ids_used = [s["id"] for s in signals]

    if batch:
        # Batch mode — score everything as 0, mark needs_review
        for dim in dimensions:
            dimension_scores[dim["key"]] = {
                "score": 0,
                "weight": dim["weight"],
                "evidence": "needs_review=True",
            }
    else:
        # Interactive mode
        click.echo(f"\n{'='*60}")
        click.echo(f"Scoring: {contact['canonical_label']}")
        click.echo(f"Signals available: {len(signals)}")
        click.echo(f"{'='*60}\n")

        for dim in dimensions:
            click.echo(f"\n--- {dim['label']} (weight: {dim['weight']}) ---")
            click.echo(f"Guide:\n{dim.get('guide', 'No guide available')}")

            # Show relevant signals
            click.echo("\nRelevant signals:")
            shown = 0
            for sig in signals[:10]:
                click.echo(f"  [{sig['signal_type']}] {sig.get('evidence_note', '')}")
                shown += 1
            if not shown:
                click.echo("  (no signals)")

            # Prompt for score
            while True:
                try:
                    score_input = click.prompt("Score (1-5)", type=int, default=0)
                    if 0 <= score_input <= 5:
                        break
                    click.echo("  Score must be 0-5")
                except (ValueError, click.Abort):
                    break

            evidence = click.prompt("Evidence note", default="", show_default=False)

            dimension_scores[dim["key"]] = {
                "score": score_input,
                "weight": dim["weight"],
                "evidence": evidence,
            }

            # Create score override signal
            score_payload = {
                "dimension": dim["key"],
                "score": score_input,
                "evidence": evidence,
            }
            fingerprint = compute_event_fingerprint(
                contact_id, "manual", "manual/score_override",
                f"score:{dim['key']}:{now}", score_payload
            )
            conn.execute(
                "INSERT OR IGNORE INTO signals "
                "(contact_id, identifier_id, collected_at, source, signal_type, "
                "source_event_id, event_fingerprint, payload, evidence_note) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (contact_id,
                 conn.execute("SELECT id FROM identifiers WHERE contact_id = ? LIMIT 1",
                              (contact_id,)).fetchone()["id"],
                 now, "manual", "manual/score_override",
                 f"score:{dim['key']}:{now}",
                 fingerprint,
                 json.dumps(score_payload, sort_keys=True),
                 f"Manual score for {dim['label']}: {score_input}")
            )

    # Calculate scores
    total_score = sum(d["score"] for d in dimension_scores.values())
    weighted_score = sum(
        d["score"] * d["weight"] for d in dimension_scores.values()
    )

    # Determine tier
    tier = determine_tier(weighted_score, tiers)

    # Create snapshot
    conn.execute(
        "INSERT INTO snapshots "
        "(contact_id, snapshot_ts, rubric_name, rubric_version, trigger, "
        "dimension_scores, total_score, weighted_score, tier, signals_used) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (contact_id, now, rubric_name, rubric_version, "update",
         json.dumps(dimension_scores, sort_keys=True),
         total_score, weighted_score, tier,
         json.dumps(signal_ids_used))
    )

    conn.commit()

    click.echo(f"\n✓ Snapshot created: total={total_score:.1f}, weighted={weighted_score:.2f}, tier={tier}")

    return weighted_score, tier


@click.command("update")
@click.argument("identifier", required=False)
@click.option("--all", "update_all", is_flag=True, help="Update all non-archived contacts")
@click.option("--since", default=None, help="Only contacts updated before Nd (e.g. 7d)")
@click.option("--rubric", "rubric_path", default=None, type=click.Path(exists=True),
              help="Path to rubric YAML file")
@click.option("--batch", is_flag=True, help="Batch mode — no interactive prompts")
@click.option("--dry-run", is_flag=True, help="Show what would happen without writing")
@click.option("--token", default=None, envvar="GITHUB_TOKEN", help="GitHub API token")
@click.pass_context
def update_command(ctx, identifier, update_all, since, rubric_path, batch, dry_run, token):
    """Update signals for a contact or all contacts."""
    db_path = ctx.obj["db_path"]
    conn = get_connection(db_path)

    rubric = None
    if rubric_path:
        rubric = load_rubric(rubric_path)

    failures = []

    try:
        if update_all:
            # Update all non-archived contacts
            query = "SELECT * FROM contacts WHERE archived = 0"
            params = []

            if since:
                # Parse "Nd" format
                days = int(since.rstrip("d"))
                cutoff = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')
                query += " AND last_updated < ?"
                params.append(cutoff)

            contacts = conn.execute(query, params).fetchall()
            click.echo(f"Updating {len(contacts)} contacts...")

            for contact in contacts:
                contact_id = contact["id"]
                label = contact["canonical_label"]
                click.echo(f"\n--- {label} ---")

                try:
                    if dry_run:
                        click.echo(f"  [dry-run] Would re-collect signals for {label}")
                        continue

                    new_count, existing_count, errors = collect_signals_for_contact(
                        conn, contact_id, token
                    )
                    click.echo(f"  {new_count} new signals found / {existing_count} already known")

                    if errors:
                        for err in errors:
                            click.echo(f"  ⚠ {err}", err=True)
                            failures.append(f"{label}: {err}")

                    if rubric:
                        run_scoring(conn, contact_id, rubric, batch=batch)

                except Exception as e:
                    failures.append(f"{label}: {e}")
                    click.echo(f"  ✗ Error: {e}", err=True)
                    continue

            conn.commit()

            if failures:
                click.echo(f"\n⚠ {len(failures)} failures:")
                for f in failures:
                    click.echo(f"  - {f}", err=True)
                sys.exit(1)
            else:
                click.echo("\n✓ All contacts updated successfully")

        elif identifier:
            # Update single contact
            if ":" not in identifier:
                raise click.ClickException("Identifier must be in platform:value format")

            platform, _, value = identifier.partition(":")
            ident_row = conn.execute(
                "SELECT * FROM identifiers WHERE platform = ? AND identifier_value = ?",
                (platform, value)
            ).fetchone()

            if not ident_row:
                raise click.ClickException(f"Identifier not found: {identifier}")

            contact_id = ident_row["contact_id"]
            contact = conn.execute(
                "SELECT * FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()

            click.echo(f"Updating {contact['canonical_label']}...")

            if dry_run:
                click.echo("[dry-run] Would re-collect signals")
                # Still collect to show summary
                new_count, existing_count, errors = collect_signals_for_contact(
                    conn, contact_id, token
                )
                click.echo(f"{new_count} new signals found / {existing_count} already known")
                conn.rollback()
                return

            new_count, existing_count, errors = collect_signals_for_contact(
                conn, contact_id, token
            )
            click.echo(f"{new_count} new signals found / {existing_count} already known")

            if errors:
                for err in errors:
                    click.echo(f"⚠ {err}", err=True)

            if rubric:
                run_scoring(conn, contact_id, rubric, batch=batch)

            conn.commit()
            click.echo("✓ Update complete")

        else:
            raise click.ClickException("Provide an identifier or use --all")

    except SystemExit:
        raise
    except click.ClickException:
        raise
    except Exception as e:
        conn.rollback()
        raise click.ClickException(str(e))
    finally:
        conn.close()
