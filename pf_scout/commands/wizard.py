"""pf-scout wizard — interactive setup guide for new users."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import requests

from ..schema import init_db
from ..db import get_connection
from ..fingerprint import compute_event_fingerprint
from ..collectors.github import GitHubCollector


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _banner(text: str):
    """Print a section banner."""
    width = 56
    bar = "━" * width
    click.echo(f"\n{bar}")
    click.echo(f"  {text}")
    click.echo(f"{bar}\n")


def _step_init_workspace(db_path: str, auto_yes: bool) -> str:
    """Step 1: Initialize the workspace directory and database.

    Returns the resolved db_path.
    """
    click.echo("Step 1/5: Initialize workspace\n")

    default_dir = os.path.expanduser("~/.pf-scout")
    default_db = os.path.join(default_dir, "contacts.db")

    if db_path and db_path != default_db:
        # --db was explicitly passed, use it
        resolved = db_path
    elif auto_yes:
        resolved = default_db
    else:
        answer = click.prompt(
            "Where should pf-scout store your database?",
            default=default_dir,
            show_default=True,
        )
        answer = os.path.expanduser(answer)
        if answer.endswith(".db"):
            resolved = answer
        else:
            resolved = os.path.join(answer, "contacts.db")

    db_dir = os.path.dirname(resolved)
    os.makedirs(db_dir, exist_ok=True)

    # Write .gitignore
    gitignore_path = os.path.join(db_dir, ".gitignore")
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, "w") as f:
            f.write("contacts.db\n")

    conn = init_db(resolved)
    conn.close()

    click.echo(f"✅ Workspace initialized at {db_dir}/")
    click.echo("   contacts.db is gitignored by default\n")

    return resolved


def _step_github_token(auto_yes: bool) -> str | None:
    """Step 2: Validate a GitHub personal access token.

    Returns the validated token or None.
    """
    click.echo("Step 2/5: GitHub token\n")
    click.echo(
        "GitHub is your first signal source. A token lets pf-scout\n"
        "collect commit history and profiles.\n"
    )

    if auto_yes:
        # In --yes mode, try env var
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            click.echo("Skipped. Set GITHUB_TOKEN env var later to enable GitHub collection.\n")
            return None
    else:
        token = click.prompt(
            "GitHub personal access token (read:user, read:org)?",
            default="skip",
            show_default=True,
            hide_input=True,
        )
        if not token or token.strip().lower() == "skip":
            click.echo("Skipped. Set GITHUB_TOKEN env var later to enable GitHub collection.\n")
            return None

    # Validate token
    try:
        resp = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            username = resp.json().get("login", "unknown")
            click.echo(f"✅ GitHub token valid. Authenticated as: {username}\n")
            return token
        else:
            click.echo("⚠ Token rejected by GitHub. You can set GITHUB_TOKEN later.\n")
            return None
    except requests.RequestException:
        click.echo("⚠ Could not reach GitHub API. You can set GITHUB_TOKEN later.\n")
        return None


def _step_seed_github(db_path: str, token: str, auto_yes: bool) -> tuple[int, int]:
    """Step 3: Seed contacts from a GitHub org.

    Only called when a valid token exists.
    Returns (contacts_created, signals_inserted).
    """
    click.echo("Step 3/5: Seed from GitHub org\n")

    if auto_yes:
        org = "postfiatorg"
    else:
        org = click.prompt(
            "Seed contacts from a GitHub org? Enter org name or skip",
            default="postfiatorg",
            show_default=True,
        )
        if not org or org.strip().lower() == "skip":
            click.echo("Skipped. Run: pf-scout seed github --org postfiatorg\n")
            return (0, 0)

    click.echo(f"Seeding {org}...")

    conn = get_connection(db_path)
    collector = GitHubCollector()
    contacts_created = 0
    signals_inserted = 0

    try:
        identifiers = collector.discover(org, token)
        click.echo(f"  found {len(identifiers)} contributors")

        for platform, ident_value in identifiers:
            now = _now_utc()

            existing = conn.execute(
                "SELECT id, contact_id FROM identifiers "
                "WHERE platform = ? AND identifier_value = ?",
                (platform, ident_value),
            ).fetchone()

            if existing:
                contact_id = existing["contact_id"]
                ident_id = existing["id"]
            else:
                contact_id = str(uuid.uuid4())
                ident_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO contacts (id, canonical_label, first_seen, last_updated) "
                    "VALUES (?, ?, ?, ?)",
                    (contact_id, ident_value, now, now),
                )
                conn.execute(
                    "INSERT INTO identifiers "
                    "(id, contact_id, platform, identifier_value, is_primary, "
                    "first_seen, last_seen, link_confidence, link_source) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (ident_id, contact_id, platform, ident_value, 1, now, now, 1.0, "wizard"),
                )
                contacts_created += 1

            collected = collector.collect(ident_value, contact_id, token)
            for sig in collected:
                fingerprint = compute_event_fingerprint(
                    contact_id, sig.source, sig.signal_type,
                    sig.source_event_id, sig.payload,
                )
                payload_json = json.dumps(sig.payload, sort_keys=True, ensure_ascii=True)
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO signals "
                    "(contact_id, identifier_id, collected_at, signal_ts, source, signal_type, "
                    "source_event_id, event_fingerprint, payload, evidence_note) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (contact_id, ident_id, now, sig.signal_ts, sig.source, sig.signal_type,
                     sig.source_event_id, fingerprint, payload_json, sig.evidence_note),
                )
                if cursor.rowcount > 0:
                    signals_inserted += 1

            conn.execute(
                "UPDATE identifiers SET last_seen = ? WHERE id = ?", (now, ident_id)
            )
            conn.execute(
                "UPDATE contacts SET last_updated = ? WHERE id = ?", (now, contact_id)
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        click.echo(f"⚠ Seeding failed: {e}")
        click.echo("  You can retry later: pf-scout seed github --org " + org + "\n")
        return (0, 0)
    finally:
        conn.close()

    click.echo(f"✅ Seeded {contacts_created} contacts, {signals_inserted} signals\n")
    return (contacts_created, signals_inserted)


def _step_pf_context(db_path: str, auto_yes: bool) -> str | None:
    """Step 4: Fetch the user's PF Context document.

    Returns the version label (date string) if set, else None.
    """
    click.echo("Step 4/5: PF Context\n")
    click.echo(
        "Post Fiat Context documents are the richest fit signal —\n"
        "each contributor's stated Value, Strategy, and Tactics.\n"
    )

    if auto_yes:
        cookie = os.environ.get("PF_SESSION_COOKIE")
        if not cookie:
            click.echo("Skipped. Run: pf-scout set-context --cookie \"$PF_SESSION_COOKIE\"\n")
            return None
    else:
        cookie = click.prompt(
            "Do you have a Post Fiat session cookie to fetch Context documents?",
            default="skip",
            show_default=True,
            hide_input=True,
        )
        if not cookie or cookie.strip().lower() == "skip":
            click.echo("Skipped. Run: pf-scout set-context --cookie \"$PF_SESSION_COOKIE\"\n")
            return None

    # Validate by hitting the context endpoint
    try:
        resp = requests.get(
            "https://tasknode.postfiat.org/context",
            headers={
                "Cookie": cookie,
                "User-Agent": "pf-scout/0.1.0",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            click.echo("⚠ Cookie not accepted. You can set PF_SESSION_COOKIE later.\n")
            return None

        raw_markdown = resp.text
    except requests.RequestException:
        click.echo("⚠ Could not reach tasknode. You can set PF_SESSION_COOKIE later.\n")
        return None

    # Write context files
    import hashlib

    scout_dir = Path(db_path).parent
    context_path = scout_dir / "my-context.md"
    state_path = scout_dir / "context-state.json"

    word_count = len(raw_markdown.split())
    content_hash = hashlib.sha256(raw_markdown.encode()).hexdigest()
    version_label = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    scout_dir.mkdir(parents=True, exist_ok=True)
    context_path.write_text(raw_markdown)
    state = {
        "fetched_at": _now_utc(),
        "content_hash": f"sha256:{content_hash}",
        "source": "tasknode",
        "version_label": version_label,
        "word_count": word_count,
    }
    state_path.write_text(json.dumps(state, indent=2))

    click.echo(f"✅ Your Context fetched ({word_count} words). Recruiter lens is set.\n")
    return version_label


def _step_choose_rubric(auto_yes: bool) -> tuple[str, str, str, int]:
    """Step 5: Choose a rubric file.

    Returns (rubric_path, rubric_name, rubric_version, dimensions_count).
    """
    click.echo("Step 5/5: Choose a rubric\n")

    # Find available rubrics
    rubrics_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "rubrics")
    rubric_files = []
    if os.path.isdir(rubrics_dir):
        rubric_files = sorted(
            f for f in os.listdir(rubrics_dir) if f.endswith((".yaml", ".yml"))
        )

    if not rubric_files:
        click.echo("  No rubrics found in rubrics/ directory.")
        click.echo("  Add a YAML rubric file and re-run.\n")
        return ("", "unknown", "0", 0)

    # List available rubrics
    click.echo("  Available rubrics:")
    for i, name in enumerate(rubric_files, 1):
        click.echo(f"    {i}. rubrics/{name}")
    click.echo()

    default_rubric = f"rubrics/{rubric_files[0]}"

    if auto_yes:
        chosen = default_rubric
    else:
        chosen = click.prompt(
            "Which rubric?",
            default=default_rubric,
            show_default=True,
        )

    # Load rubric metadata
    try:
        import yaml  # type: ignore

        rubric_path = chosen
        # Resolve relative to project root
        if not os.path.isabs(rubric_path):
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            rubric_path_abs = os.path.join(project_root, rubric_path)
        else:
            rubric_path_abs = rubric_path

        with open(rubric_path_abs) as f:
            rubric = yaml.safe_load(f)

        rubric_name = rubric.get("name", "unknown")
        rubric_version = rubric.get("version", "0")
        rubric_desc = rubric.get("description", "")
        dimensions = rubric.get("dimensions", [])
        dim_count = len(dimensions)

        display_name = f"{rubric_name} {rubric_desc} v{rubric_version}"
        click.echo(f"✅ Using rubric: {display_name} ({dim_count} dimensions)\n")
        return (chosen, rubric_name, rubric_version, dim_count)
    except ImportError:
        click.echo(f"✅ Using rubric: {chosen}\n")
        return (chosen, "unknown", "0", 0)
    except Exception:
        click.echo(f"✅ Using rubric: {chosen}\n")
        return (chosen, "unknown", "0", 0)


@click.command("wizard")
@click.option("--yes", "-y", "auto_yes", is_flag=True, default=False,
              help="Skip all prompts and use defaults (for CI/scripting)")
@click.pass_context
def wizard_cmd(ctx, auto_yes):
    """Interactive setup wizard for first-time pf-scout configuration."""

    db_path = ctx.obj.get("db_path")

    # ── Step 0: Welcome ──────────────────────────────────────
    _banner("pf-scout wizard — contact intelligence for Post Fiat")
    click.echo(
        "pf-scout builds a persistent, growing profile for each\n"
        "Post Fiat contributor. Signals compound over time.\n"
    )
    if not auto_yes:
        click.echo("Let's get you set up. Press Ctrl+C to exit at any time.\n")

    # ── Step 1: Init workspace ────────────────────────────────
    try:
        db_path = _step_init_workspace(db_path, auto_yes)
    except Exception as e:
        click.echo(f"⚠ Init failed: {e}")
        click.echo("  Continuing with remaining steps...\n")
        if not db_path:
            db_path = os.path.expanduser("~/.pf-scout/contacts.db")

    # ── Step 2: GitHub token ──────────────────────────────────
    github_token = None
    try:
        github_token = _step_github_token(auto_yes)
    except Exception as e:
        click.echo(f"⚠ GitHub token step failed: {e}\n")

    # ── Step 3: Seed from GitHub org ──────────────────────────
    contacts_seeded = 0
    signals_seeded = 0
    if github_token:
        try:
            contacts_seeded, signals_seeded = _step_seed_github(
                db_path, github_token, auto_yes
            )
        except Exception as e:
            click.echo(f"⚠ Seeding failed: {e}\n")
    else:
        click.echo("Step 3/5: Seed from GitHub org\n")
        click.echo("  (Skipped — no GitHub token provided)\n")

    # ── Step 4: PF Context ────────────────────────────────────
    context_version = None
    try:
        context_version = _step_pf_context(db_path, auto_yes)
    except Exception as e:
        click.echo(f"⚠ Context step failed: {e}\n")

    # ── Step 5: Choose a rubric ───────────────────────────────
    rubric_path = ""
    rubric_display = "not set"
    try:
        rubric_path, rubric_name, rubric_version, dim_count = _step_choose_rubric(auto_yes)
        if rubric_name != "unknown":
            rubric_display = f"{rubric_name} v{rubric_version}"
    except Exception as e:
        click.echo(f"⚠ Rubric step failed: {e}\n")

    # ── Step 6: Summary ──────────────────────────────────────
    db_display = db_path.replace(os.path.expanduser("~"), "~")
    context_display = context_version if context_version else "not set"
    contacts_display = f"{contacts_seeded} seeded" if contacts_seeded else "0"

    _banner("Setup complete 🎉")
    click.echo(f"  Database:  {db_display}")
    click.echo(f"  Contacts:  {contacts_display}")
    click.echo(f"  Context:   {context_display}")
    click.echo(f"  Rubric:    {rubric_display}")
    click.echo()
    click.echo("  Next steps:")
    click.echo("    pf-scout list                                          # view all contacts")
    click.echo("    pf-scout export --output backup.json                   # backup your data")
    click.echo("    pf-scout show github:allenday                         # view a contact card")

    rubric_flag = f" --rubric {rubric_path}" if rubric_path else ""
    click.echo(f"    pf-scout update github:allenday{rubric_flag}  # score")
    click.echo(f"    pf-scout rerank{rubric_flag}                   # rank by context")
    click.echo(f"    pf-scout report{rubric_flag} --output report.md")
    click.echo()
